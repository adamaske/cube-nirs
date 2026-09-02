<script>
  import { onMount } from 'svelte';
  import { state as snap, tick, connected, events, send, advance } from '../lib/ws.js';

  // ---- setup form ----
  let cfg = $state({
    subject: 1,
    session: 1,
    trials: 5,
    rest_pre: 20,
    rest_post: 45,
    scramble_len: 20,
    seed: '',
    comment: '',
    stream_name: 'Trigger',
    no_lsl: false,
    no_beep: false,
  });
  let advanceMode = $state('both');
  let lsl = $state(null);
  let sessionTouched = $state(false);

  const live = $derived(
    !['idle', 'done', 'aborted'].includes($snap.state)
  );
  const inSession = $derived($snap.state !== 'idle');

  onMount(async () => {
    try {
      const d = await (await fetch('/api/config')).json();
      cfg = { ...cfg, ...d.config, seed: d.config.seed ?? '' };
      advanceMode = d.advance_mode;
    } catch {}
    try {
      lsl = await (await fetch('/api/lsl-status')).json();
    } catch {}
    await refreshSessionNumber();
  });

  async function refreshSessionNumber() {
    if (sessionTouched) return;
    try {
      const d = await (await fetch(`/api/next-session?subject=${cfg.subject}`)).json();
      cfg.session = d.session;
    } catch {}
  }

  function start() {
    send({
      cmd: 'start',
      advance_mode: advanceMode,
      config: {
        ...cfg,
        seed: cfg.seed === '' ? null : Number(cfg.seed),
        rest_pre: Number(cfg.rest_pre),
        rest_post: Number(cfg.rest_post),
      },
    });
  }

  function doAdvance() {
    advance($snap.state, 'experimenter');
  }

  function doAbort() {
    if (confirm('Abort the session? The recording cannot be resumed.')) {
      send({ cmd: 'abort' });
    }
  }

  function onKey(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (e.code === 'Space' && live) {
      e.preventDefault();
      doAdvance();
    }
  }

  const SELF_PACED = ['configured', 'plan', 'solve', 'break'];
  const advanceLabel = $derived(
    {
      configured: 'START SESSION (Aurora recording?)',
      plan: 'ADVANCE — first turn made',
      solve: 'ADVANCE — cube is down',
      break: 'ADVANCE — start next trial',
    }[$snap.state] ?? 'ADVANCE'
  );

  const stateLabel = $derived(
    {
      idle: 'IDLE',
      configured: 'READY — scramble the cube',
      rest_pre: 'REST (pre)',
      plan: 'PLAN',
      solve: 'SOLVE',
      rest_post: 'REST (post)',
      break: 'BREAK — scramble for next trial',
      done: 'SESSION COMPLETE',
      aborted: 'ABORTED',
    }[$snap.state] ?? $snap.state
  );

  function fmt(x, digits = 1) {
    return x == null || x === '' ? '—' : Number(x).toFixed(digits);
  }
</script>

<svelte:window on:keydown={onKey} />

<main>
  <header>
    <h1>cube-nirs session</h1>
    <span class="conn" class:ok={$connected}>{$connected ? 'connected' : 'disconnected'}</span>
  </header>

  {#if !live}
    <section class="setup">
      <h2>New session</h2>
      <div class="grid">
        <label>subject
          <input type="number" min="1" bind:value={cfg.subject} onchange={refreshSessionNumber} />
        </label>
        <label>session
          <input type="number" min="1" bind:value={cfg.session}
                 oninput={() => (sessionTouched = true)} />
        </label>
        <label>trials
          <input type="number" min="1" bind:value={cfg.trials} />
        </label>
        <label>rest pre (s)
          <input type="number" min="0" step="1" bind:value={cfg.rest_pre} />
        </label>
        <label>rest post (s)
          <input type="number" min="0" step="1" bind:value={cfg.rest_post} />
        </label>
        <label>scramble length
          <input type="number" min="1" bind:value={cfg.scramble_len} />
        </label>
        <label>seed (blank = auto)
          <input type="number" bind:value={cfg.seed} />
        </label>
        <label>stream name
          <input type="text" bind:value={cfg.stream_name} />
        </label>
        <label>advance source
          <select bind:value={advanceMode}>
            <option value="both">both</option>
            <option value="experimenter">experimenter only</option>
            <option value="subject">subject only</option>
          </select>
        </label>
        <label class="wide">comment
          <input type="text" bind:value={cfg.comment} />
        </label>
        <label class="check"><input type="checkbox" bind:checked={cfg.no_lsl} /> no LSL (dry run)</label>
        <label class="check"><input type="checkbox" bind:checked={cfg.no_beep} /> no beep</label>
      </div>
      <p class="lsl">
        LSL:
        {#if lsl == null}checking…{:else if lsl.available}<span class="ok">pylsl available</span>
        {:else}<span class="bad">pylsl unavailable — {lsl.error}</span>{/if}
      </p>
      <button class="big start" onclick={start}>ARM SESSION</button>
      {#if $snap.state === 'done' || $snap.state === 'aborted'}
        <p class="note">Previous session {$snap.state}. Results below.</p>
      {/if}
    </section>
  {/if}

  {#if inSession}
    <section class="live">
      <div class="banner state-{$snap.state}">
        <div class="statename">{stateLabel}</div>
        <div class="trial">
          {#if $snap.trial > 0}trial {$snap.trial} / {$snap.trials_planned}{/if}
        </div>
        <div class="clock">
          {#if $tick?.remaining != null}{fmt($tick.remaining)} s left{/if}
          {#if $tick?.elapsed != null}{fmt($tick.elapsed)} s{/if}
        </div>
      </div>

      {#if ['configured', 'break'].includes($snap.state)}
        <div class="scramble">
          <h3>Scramble</h3>
          <code>{$snap.scramble}</code>
          {#if $snap.state === 'configured'}
            <p class="note">Scramble the cube, confirm Aurora is recording with the
              '{cfg.stream_name}' stream selected, then start.</p>
          {/if}
        </div>
      {/if}

      {#if live}
        <div class="controls">
          <button class="big" disabled={!SELF_PACED.includes($snap.state)} onclick={doAdvance}>
            {advanceLabel}<small>(spacebar)</small>
          </button>
          <button class="dnf" disabled={$snap.state !== 'solve'}
                  onclick={() => send({ cmd: 'dnf' })}>
            DNF {#if $snap.dnf_pending}✓{/if}
          </button>
          <button class="abort" onclick={doAbort}>ABORT</button>
        </div>
      {/if}

      <div class="results">
        <h3>Trials</h3>
        <table>
          <thead><tr><th>#</th><th>plan (s)</th><th>solve (s)</th><th>DNF</th><th>break (s)</th></tr></thead>
          <tbody>
            {#each $snap.results ?? [] as t}
              <tr class:dnfrow={t.dnf}>
                <td>{t.trial}</td>
                <td>{fmt(t.plan_s)}</td>
                <td>{fmt(t.solve_s)}</td>
                <td>{t.dnf ? 'DNF' : ''}</td>
                <td>{fmt(t.break_s)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      <div class="eventlog">
        <h3>Events</h3>
        <ul>
          {#each [...$events].reverse() as e}
            <li class={e.kind}><span class="t">{e.t}</span> {e.text}</li>
          {/each}
        </ul>
      </div>
    </section>
  {/if}

  <footer>
    <a href="/subject" target="_blank">subject display</a> ·
    <a href="/dashboard" target="_blank">dashboard</a>
  </footer>
</main>

<style>
  :global(body) {
    margin: 0;
    background: #16181d;
    color: #e6e6e6;
    font-family: system-ui, sans-serif;
  }
  main { max-width: 900px; margin: 0 auto; padding: 1rem 1.5rem 3rem; }
  header { display: flex; align-items: baseline; justify-content: space-between; }
  h1 { font-size: 1.2rem; letter-spacing: 0.05em; }
  h2, h3 { font-size: 1rem; color: #9fb4c7; }
  .conn { color: #d06060; font-size: 0.85rem; }
  .conn.ok { color: #6fbf73; }

  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.6rem 1rem; }
  label { display: flex; flex-direction: column; font-size: 0.8rem; color: #9aa3ad; gap: 0.2rem; }
  label.wide { grid-column: span 2; }
  label.check { flex-direction: row; align-items: center; gap: 0.4rem; margin-top: 1rem; }
  input, select {
    background: #22252c; color: #e6e6e6; border: 1px solid #3a3f48;
    border-radius: 4px; padding: 0.35rem 0.5rem; font-size: 0.95rem;
  }
  .lsl { font-size: 0.85rem; }
  .ok { color: #6fbf73; }
  .bad { color: #d06060; }
  .note { color: #9aa3ad; font-size: 0.85rem; }

  button { cursor: pointer; border: none; border-radius: 6px; font-size: 1rem; }
  button:disabled { opacity: 0.35; cursor: default; }
  .big {
    padding: 1rem 2rem; font-size: 1.25rem; font-weight: 600;
    background: #2f6fb0; color: white; display: flex; flex-direction: column; align-items: center;
  }
  .big small { font-size: 0.7rem; font-weight: 400; opacity: 0.7; }
  .start { margin-top: 1rem; background: #3d8b40; }
  .controls { display: flex; gap: 1rem; margin: 1.2rem 0; align-items: stretch; }
  .dnf { background: #a8842c; color: white; padding: 0 1.5rem; }
  .abort { background: #7a2727; color: white; padding: 0 1.5rem; margin-left: auto; }

  .banner {
    display: flex; justify-content: space-between; align-items: baseline;
    background: #22252c; border-left: 6px solid #2f6fb0;
    padding: 0.8rem 1rem; margin: 1rem 0; border-radius: 4px;
  }
  .banner.state-solve { border-color: #3d8b40; }
  .banner.state-plan { border-color: #a8842c; }
  .banner.state-rest_pre, .banner.state-rest_post { border-color: #666; }
  .banner.state-aborted { border-color: #d06060; }
  .statename { font-size: 1.4rem; font-weight: 700; }
  .clock { font-variant-numeric: tabular-nums; font-size: 1.4rem; }

  .scramble code {
    display: block; font-size: 1.3rem; background: #22252c;
    padding: 0.8rem; border-radius: 4px; letter-spacing: 0.08em;
  }
  table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
  th, td { text-align: right; padding: 0.3rem 0.6rem; border-bottom: 1px solid #2c313a; }
  th:first-child, td:first-child { text-align: left; }
  .dnfrow { color: #d06060; }

  .eventlog ul {
    list-style: none; padding: 0; max-height: 14rem; overflow-y: auto;
    font-family: ui-monospace, monospace; font-size: 0.78rem;
  }
  .eventlog .t { color: #6c7480; margin-right: 0.5rem; }
  .eventlog .rejected, .eventlog .error { color: #d0a060; }
  .eventlog .ended { color: #9fb4c7; }
  .eventlog .dnf { color: #d06060; }

  footer { margin-top: 2rem; font-size: 0.85rem; }
  footer a { color: #7aa7d0; }
</style>

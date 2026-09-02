<script>
  import { onMount } from 'svelte';

  let sessions = $state([]);
  let solves = $state([]);
  let selected = $state(null); // log dict from /api/sessions/{log}
  let selectedLog = $state(null);
  let error = $state(null);

  onMount(async () => {
    try {
      const d = await (await fetch('/api/sessions')).json();
      sessions = d.sessions;
      solves = d.solves;
    } catch (e) {
      error = String(e);
    }
  });

  async function open(row) {
    try {
      selected = await (await fetch(`/api/sessions/${row.log}`)).json();
      selectedLog = row.log;
    } catch (e) {
      error = String(e);
    }
  }

  // ---- trend chart: solve/plan time per trial across all sessions ----
  const W = 860, H = 300, PAD = 40;
  const points = $derived(
    solves.map((r, i) => ({
      x: i,
      session: Number(r.session),
      trial: Number(r.trial),
      solve: Number(r.solve_s),
      plan: Number(r.plan_s),
      dnf: r.dnf === '1',
    }))
  );
  const ymax = $derived(Math.max(10, ...points.map((p) => Math.max(p.solve, p.plan))) * 1.1);
  const xs = (i) => PAD + (points.length < 2 ? 0 : (i * (W - 2 * PAD)) / (points.length - 1));
  const ys = $derived((v) => H - PAD - (v / ymax) * (H - 2 * PAD));
  // vertical separators where a new session starts
  const sessionStarts = $derived(
    points.filter((p, i) => i > 0 && points[i - 1].session !== p.session).map((p) => p.x)
  );
  function path(key) {
    return points
      .filter((p) => !p.dnf)
      .map((p, i) => `${i === 0 ? 'M' : 'L'}${xs(p.x)},${ys(p[key])}`)
      .join(' ');
  }

  function fmtMarker(m, t0) {
    const t = (m.t_lsl ?? m.t_wall) - t0;
    return t.toFixed(1);
  }
</script>

<main>
  <h1>cube-nirs dashboard</h1>
  {#if error}<p class="bad">{error}</p>{/if}

  {#if points.length}
    <section>
      <h2>Solve time per trial (all sessions)</h2>
      <svg viewBox="0 0 {W} {H}">
        {#each [0, 0.25, 0.5, 0.75, 1] as f}
          <line x1={PAD} x2={W - PAD} y1={ys(f * ymax)} y2={ys(f * ymax)} class="grid" />
          <text x={PAD - 6} y={ys(f * ymax) + 4} class="ylab">{(f * ymax).toFixed(0)}</text>
        {/each}
        {#each sessionStarts as x}
          <line x1={xs(x)} x2={xs(x)} y1={PAD} y2={H - PAD} class="sep" />
        {/each}
        <path d={path('plan')} class="plan" />
        <path d={path('solve')} class="solve" />
        {#each points as p}
          {#if p.dnf}
            <text x={xs(p.x)} y={ys(p.solve)} class="dnfmark">✕</text>
          {:else}
            <circle cx={xs(p.x)} cy={ys(p.solve)} r="3" class="solvedot" />
            <circle cx={xs(p.x)} cy={ys(p.plan)} r="2.5" class="plandot" />
          {/if}
        {/each}
        <text x={W - PAD} y={PAD - 8} class="legend solve-t">— solve</text>
        <text x={W - PAD - 90} y={PAD - 8} class="legend plan-t">— plan</text>
        <text x={W - PAD - 170} y={PAD - 8} class="legend dnf-t">✕ DNF</text>
      </svg>
    </section>
  {/if}

  <section>
    <h2>Sessions</h2>
    {#if sessions.length === 0}
      <p class="note">No sessions recorded yet.</p>
    {:else}
      <table>
        <thead>
          <tr><th>subject</th><th>session</th><th>date</th><th>trials</th>
              <th>mean solve (s)</th><th>best (s)</th><th>completed</th><th>comment</th></tr>
        </thead>
        <tbody>
          {#each sessions as r}
            <tr class="row" class:sel={r.log === selectedLog} onclick={() => open(r)}>
              <td>{r.subject}</td>
              <td>{r.session}</td>
              <td>{r.date}</td>
              <td>{r.trials_completed}/{r.trials_planned}</td>
              <td>{r.mean_solve_s}</td>
              <td>{r.best_solve_s}</td>
              <td>{r.completed === '1' ? 'yes' : 'no'}</td>
              <td class="comment">{r.comment}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </section>

  {#if selected}
    <section>
      <h2>Session detail — sub {selected.subject} ses {selected.session} ({selected.started?.slice(0, 16)})</h2>
      <h3>Trials</h3>
      <table>
        <thead><tr><th>#</th><th>plan (s)</th><th>solve (s)</th><th>DNF</th><th>break (s)</th><th>scramble</th></tr></thead>
        <tbody>
          {#each selected.trials as t}
            <tr class:dnfrow={t.dnf}>
              <td>{t.trial}</td><td>{t.plan_s}</td><td>{t.solve_s}</td>
              <td>{t.dnf ? 'DNF' : ''}</td><td>{t.break_s ?? ''}</td>
              <td class="scr">{t.scramble}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      <h3>Marker timeline</h3>
      <table>
        <thead><tr><th>t (s)</th><th>code</th><th>name</th></tr></thead>
        <tbody>
          {#each selected.markers as m}
            <tr>
              <td>{fmtMarker(m, selected.markers[0].t_lsl ?? selected.markers[0].t_wall)}</td>
              <td>{m.code}</td><td>{m.name}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </section>
  {/if}
</main>

<style>
  :global(body) {
    margin: 0; background: #16181d; color: #e6e6e6;
    font-family: system-ui, sans-serif;
  }
  main { max-width: 920px; margin: 0 auto; padding: 1rem 1.5rem 3rem; }
  h1 { font-size: 1.2rem; letter-spacing: 0.05em; }
  h2, h3 { font-size: 1rem; color: #9fb4c7; }
  .note { color: #9aa3ad; }
  .bad { color: #d06060; }

  svg { width: 100%; height: auto; background: #1b1e24; border-radius: 6px; }
  .grid { stroke: #2c313a; stroke-width: 1; }
  .sep { stroke: #3a3f48; stroke-dasharray: 3 3; }
  .ylab { fill: #6c7480; font-size: 10px; text-anchor: end; }
  path { fill: none; stroke-width: 2; }
  .solve { stroke: #5b9bd5; }
  .plan { stroke: #a8842c; }
  .solvedot { fill: #5b9bd5; }
  .plandot { fill: #a8842c; }
  .dnfmark { fill: #d06060; font-size: 12px; text-anchor: middle; }
  .legend { font-size: 11px; text-anchor: end; }
  .solve-t { fill: #5b9bd5; }
  .plan-t { fill: #a8842c; }
  .dnf-t { fill: #d06060; }

  table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
  th, td { text-align: right; padding: 0.3rem 0.6rem; border-bottom: 1px solid #2c313a; }
  th:first-child, td:first-child { text-align: left; }
  td.comment, td.scr { text-align: left; font-size: 0.75rem; color: #9aa3ad; }
  .row { cursor: pointer; }
  .row:hover { background: #22252c; }
  .row.sel { background: #263041; }
  .dnfrow { color: #d06060; }
</style>

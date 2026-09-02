<script>
  import { state as snap, tick, advance } from '../lib/ws.js';

  // The display itself is a visual stimulus (occipital recording):
  // constant mid-grey background, no motion, no numbers during trials.
  const showButton = $derived(
    ['subject', 'both'].includes($snap.advance_mode) &&
      ['plan', 'solve', 'break'].includes($snap.state)
  );
  const buttonLabel = $derived(
    {
      plan: 'PRESS AT FIRST TURN',
      solve: 'PRESS WHEN CUBE IS DOWN',
      break: 'START NEXT TRIAL',
    }[$snap.state] ?? 'ADVANCE'
  );
</script>

<main>
  {#if $snap.state === 'rest_pre' || $snap.state === 'rest_post'}
    <div class="cross">+</div>
  {:else if $snap.state === 'plan'}
    <div class="word">PLAN</div>
  {:else if $snap.state === 'solve'}
    <div class="word">SOLVE</div>
  {:else if $snap.state === 'break'}
    <div class="break">
      <div class="scramble">{$snap.scramble}</div>
      <div class="elapsed">{$tick?.elapsed != null ? Math.floor($tick.elapsed) + ' s' : ''}</div>
    </div>
  {:else if $snap.state === 'done'}
    <div class="word small">Session complete.</div>
  {:else if $snap.state === 'configured'}
    <div class="word small">Waiting to start…</div>
  {:else if $snap.state === 'aborted'}
    <div class="word small">Session stopped.</div>
  {:else}
    <div class="cross dim">+</div>
  {/if}

  {#if showButton}
    <button onclick={() => advance($snap.state, 'subject')}>{buttonLabel}</button>
  {/if}
</main>

<style>
  :global(html, body) { height: 100%; }
  :global(body) {
    margin: 0;
    /* constant luminance across all in-trial states */
    background: #7f7f7f;
    color: #1a1a1a;
    font-family: system-ui, sans-serif;
    overflow: hidden;
  }
  main {
    height: 100vh; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 4vh;
  }
  .cross { font-size: 12vh; font-weight: 300; }
  .cross.dim { opacity: 0.4; }
  .word { font-size: 14vh; font-weight: 700; letter-spacing: 0.06em; }
  .word.small { font-size: 6vh; font-weight: 400; }
  .break { text-align: center; }
  .scramble {
    font-family: ui-monospace, monospace; font-size: 6vh;
    max-width: 90vw; line-height: 1.4;
  }
  .elapsed { margin-top: 3vh; font-size: 4vh; font-variant-numeric: tabular-nums; }
  button {
    font-size: 4.5vh; padding: 3vh 8vw; border: 2px solid #1a1a1a;
    border-radius: 12px; background: #8f8f8f; color: #1a1a1a; cursor: pointer;
  }
  button:active { background: #999; }
</style>

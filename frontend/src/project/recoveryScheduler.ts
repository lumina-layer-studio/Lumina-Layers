/** Debounced, single-flight recovery. Busy work and failed writes keep their request. */
export function createRecoveryScheduler(options: {
  needed: () => boolean;
  ready: () => boolean;
  save: () => Promise<void>;
  onError: (error: unknown) => void;
  delay?: number;
  retryDelay?: number;
}) {
  const delay = options.delay ?? 5000;
  const retryDelay = options.retryDelay ?? 2000;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let pending = false;
  let stopped = false;
  let failures = 0;
  let running: Promise<void> | null = null;
  let requestedAt = 0;

  const schedule = (ms: number) => {
    clearTimeout(timer);
    timer = setTimeout(() => { timer = undefined; void flush(); }, ms);
  };
  const flush = async () => {
    if (stopped || running || !pending) return;
    if (!options.needed()) { pending = false; return; }
    if (!options.ready()) { schedule(retryDelay); return; }
    pending = false;
    running = (async () => {
      try { await options.save(); failures = 0; }
      catch (error) {
        pending = true;
        failures += 1;
        options.onError(error);
      }
    })();
    await running;
    running = null;
    if (!stopped && pending) schedule(failures ? Math.min(30_000, retryDelay * 2 ** Math.min(failures - 1, 4)) : delay);
  };
  return {
    request() {
      stopped = false;
      if (!pending) requestedAt = Date.now();
      pending = true;
      failures = 0;
      if (!running) schedule(Math.max(0, Math.min(delay, 30_000 - (Date.now() - requestedAt))));
    },
    wake() { if (!stopped && pending && !running) schedule(0); },
    settled() { return running ?? Promise.resolve(); },
    stop() { stopped = true; pending = false; clearTimeout(timer); },
  };
}

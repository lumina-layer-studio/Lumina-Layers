export interface RetryAsyncOptions {
  attempts: number;
  delayMs: number;
  sleep?: (delayMs: number) => Promise<void>;
  shouldRetry?: (error: unknown) => boolean;
}

function defaultSleep(delayMs: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, delayMs);
  });
}

export async function retryAsync<T>(
  operation: () => Promise<T>,
  options: RetryAsyncOptions,
): Promise<T> {
  const { attempts, delayMs, sleep = defaultSleep, shouldRetry } = options;

  let lastError: unknown = null;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await operation();
    } catch (error) {
      lastError = error;
      if (attempt >= attempts || (shouldRetry && !shouldRetry(error))) {
        throw error;
      }
      await sleep(delayMs);
    }
  }

  throw lastError instanceof Error
    ? lastError
    : new Error("Retry operation failed");
}

import { useEffect, useState } from "react";

const WINDOW_SIZE = 3;
const NEW_SAMPLE_WEIGHT = 0.25;

interface TimeEstimate {
  scope: string;
  batch: string | null;
  receivedBytes: number;
  samples: number[];
  seconds: number | null;
}

function emptyEstimate(scope: string): TimeEstimate {
  return { scope, batch: null, receivedBytes: 0, samples: [], seconds: null };
}

/** Filter fresh measurements and retain the last estimate across gaps in telemetry. */
export function useFilteredDownloadTime(
  scope: string,
  batch: string | null,
  receivedBytes: number,
  rawSeconds: number | null,
): number | null {
  const [estimate, setEstimate] = useState(() => emptyEstimate(scope));

  useEffect(() => {
    setEstimate((previous) => {
      const current = previous.scope === scope ? previous : emptyEstimate(scope);
      if (batch === null || rawSeconds === null || !Number.isFinite(rawSeconds) || rawSeconds <= 0) {
        return current;
      }
      if (current.batch === batch && current.receivedBytes === receivedBytes) {
        return current;
      }

      // A new mirror or a retry starts a new sample window. The visible estimate
      // stays until the new window is ready.
      const recent = current.batch === batch && receivedBytes > current.receivedBytes
        ? current.samples.slice(1 - WINDOW_SIZE)
        : [];
      const samples = [...recent, rawSeconds];
      let seconds = current.seconds;
      if (samples.length === WINDOW_SIZE) {
        const median = [...samples].sort((a, b) => a - b)[1];
        seconds = seconds === null ? median : seconds + (median - seconds) * NEW_SAMPLE_WEIGHT;
      }
      return { scope, batch, receivedBytes, samples, seconds };
    });
  }, [scope, batch, receivedBytes, rawSeconds]);

  return estimate.scope === scope ? estimate.seconds : null;
}

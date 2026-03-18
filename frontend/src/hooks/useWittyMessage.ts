import { useState, useEffect, useRef } from 'react';
import { useI18n } from '../i18n/context';

const WITTY_MESSAGE_COUNT = 40;

/**
 * Custom hook to generate rotating, humorous loading messages.
 * Uses translation keys `loading_witty_1` through `loading_witty_N`.
 *
 * @param intervalMs How often to change the message (default 2500ms).
 * @param isRunning Whether the interval is currently active.
 * @returns The current translated witty message string.
 */
export function useWittyMessage(intervalMs: number = 2500, isRunning: boolean = true) {
  const { t } = useI18n();
  const [msgIndex, setMsgIndex] = useState(() => Math.floor(Math.random() * WITTY_MESSAGE_COUNT) + 1);
  const msgHistory = useRef<number[]>([msgIndex]);

  useEffect(() => {
    if (!isRunning) return;

    const interval = setInterval(() => {
      setMsgIndex(() => {
        let nextIndex;
        // Try to pick a new random index that wasn't used recently (last 3 items)
        do {
          nextIndex = Math.floor(Math.random() * WITTY_MESSAGE_COUNT) + 1;
        } while (msgHistory.current.includes(nextIndex));

        msgHistory.current.push(nextIndex);
        if (msgHistory.current.length > 3) {
          msgHistory.current.shift();
        }

        return nextIndex;
      });
    }, intervalMs);

    return () => clearInterval(interval);
  }, [intervalMs, isRunning]);

  return t(`loading_witty_${msgIndex}`);
}

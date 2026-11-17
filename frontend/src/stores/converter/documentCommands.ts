export interface DocumentCommandOptions {
  localEditor?: boolean;
  joinAsync?: boolean;
}

type Runner = <Result>(action: () => Result, blocked: () => Result, options: DocumentCommandOptions) => Result;

/** Declare history ownership beside an action, preserving its arguments/return type. */
export function createDocumentCommandWrapper(run: Runner) {
  function command<Args extends unknown[], Result>(
    action: (...args: Args) => Result,
    options: DocumentCommandOptions & { blocked: () => Result },
  ): (...args: Args) => Result;
  function command<Args extends unknown[]>(
    action: (...args: Args) => void,
    options?: DocumentCommandOptions,
  ): (...args: Args) => void;
  function command<Args extends unknown[], Result>(
    action: (...args: Args) => Result,
    options: DocumentCommandOptions & { blocked?: () => Result } = {},
  ): (...args: Args) => Result | undefined {
    return (...args) => run(() => action(...args), () => options.blocked?.(), options);
  }
  return command;
}

export type DocumentCommandWrapper = ReturnType<typeof createDocumentCommandWrapper>;

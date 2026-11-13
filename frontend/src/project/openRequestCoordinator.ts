export interface OpenRequestCoordinator {
  /** Claim a native request exactly once across all delivery channels. */
  claim(requestId: string | null): boolean;
}

export function createOpenRequestCoordinator(): OpenRequestCoordinator {
  const claimedRequestIds = new Set<string>();
  return {
    claim(requestId) {
      if (!requestId) return true;
      if (claimedRequestIds.has(requestId)) return false;
      claimedRequestIds.add(requestId);
      return true;
    },
  };
}

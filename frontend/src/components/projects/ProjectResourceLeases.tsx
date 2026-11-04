import { useSessionLease } from "../../hooks/useSessionLease";
import { useConverterStore } from "../../stores/converter";
import { useExtractorStore } from "../../stores/extractorStore";
import { useSingleStageStore } from "../../stores/singleStageStore";
import { useWorkflowRuntime } from "../../project/workflowRuntime";

function Lease({ id }: { id: string }) {
  useSessionLease(id, null);
  return null;
}
export function ProjectResourceLeases() {
  const resources = useConverterStore((state) => state.projectResourceSessionIds);
  const workflows = useWorkflowRuntime((state) => state.workflows);
  const extractor = useExtractorStore((state) => state.session_id);
  const workspace = useExtractorStore((state) => state.workspaceSessionId);
  const singleStage = useSingleStageStore((state) => state.sessionId);
  const ids = new Set([...(resources ?? []), ...Object.values(workflows).flatMap((runtime) => runtime.sessionIds ?? []), extractor, workspace].filter((id): id is string => Boolean(id) && id !== singleStage));
  return <>{[...ids].map((id) => <Lease key={id} id={id} />)}</>;
}

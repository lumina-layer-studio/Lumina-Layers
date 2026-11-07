import { beforeEach, describe, expect, it } from "vitest";
import { useProjectSessionStore } from "../stores/projectSessionStore";
import {
  createProjectRevision,
  createProjectSnapshot,
  forkProjectSnapshot,
} from "../project/identity";

describe("project session store", () => {
  beforeEach(() => {
    useProjectSessionStore.getState().reset();
  });

  it("tracks one active project and keeps later edits dirty after an older save completes", () => {
    const snapshot = createProjectSnapshot({
      name: "Draft",
      workflowKinds: ["converter"],
      documents: [
        {
          documentId: "doc",
          kind: "converter",
          schemaVersion: 1,
          payload: { source: null },
          inputRevisionIds: [],
          resourceRefs: [],
          requiredCapabilities: ["converter.v1"],
        },
      ],
    });

    useProjectSessionStore.getState().activate(snapshot);
    const savedRevisionId = snapshot.manifest.revisionId;
    useProjectSessionStore.getState().markSaved(savedRevisionId);
    useProjectSessionStore.getState().markDirty("new-revision");

    const state = useProjectSessionStore.getState();
    expect(state.activeProjectId).toBe(snapshot.manifest.projectId);
    expect(state.savedRevisionId).toBe(savedRevisionId);
    expect(state.dirty).toBe(true);
    expect(state.revisionId).toBe("new-revision");
  });

  it("increments runtime epoch so late responses can be discarded", () => {
    const first = useProjectSessionStore.getState().runtimeEpoch;
    const next = useProjectSessionStore.getState().beginRuntimeEpoch();
    expect(next).toBe(first + 1);
    expect(useProjectSessionStore.getState().runtimeEpoch).toBe(next);
  });

  it("does not let a delayed save commit over a newer edit", () => {
    const snapshot = createProjectSnapshot({
      name: "Concurrent save",
      workflowKinds: ["converter"],
      documents: [{
        documentId: "doc",
        kind: "converter",
        schemaVersion: 1,
        payload: { source: null },
        inputRevisionIds: [],
        resourceRefs: [],
        requiredCapabilities: ["converter.v1"],
      }],
    });
    useProjectSessionStore.getState().activate(snapshot);
    const expectedGeneration = useProjectSessionStore.getState().changeSequence;
    useProjectSessionStore.getState().markDirty("edit-n-plus-1");
    const saved = useProjectSessionStore.getState().commitSavedSnapshot(
      snapshot,
      expectedGeneration,
    );

    expect(saved).toBe(false);
    expect(useProjectSessionStore.getState().dirty).toBe(true);
    expect(useProjectSessionStore.getState().revisionId).toBe("edit-n-plus-1");
  });

  it("activates the new project identity after a guarded Save As commit", () => {
    const source = createProjectSnapshot({
      name: "Source project",
      workflowKinds: ["converter"],
      documents: [{
        documentId: "doc",
        kind: "converter",
        schemaVersion: 1,
        payload: { source: "A" },
        inputRevisionIds: [],
        resourceRefs: [],
        requiredCapabilities: ["converter.v1"],
      }],
    });
    useProjectSessionStore.getState().activate(source, {
      savedRevisionId: source.manifest.revisionId,
      dirty: false,
    });
    const expectedChangeSequence = useProjectSessionStore.getState().changeSequence;
    const fork = forkProjectSnapshot(source, "Copied project");

    expect(
      useProjectSessionStore.getState().commitSavedFork(
        fork,
        expectedChangeSequence,
        source.manifest.projectId,
      ),
    ).toBe(true);

    const afterFork = useProjectSessionStore.getState();
    expect(afterFork.activeProjectId).toBe(fork.manifest.projectId);
    expect(afterFork.savedRevisionId).toBe(fork.manifest.revisionId);
    expect(afterFork.dirty).toBe(false);

    const laterRevision = createProjectRevision(
      fork,
      createProjectSnapshot({
        name: "Copied project",
        workflowKinds: ["converter"],
        documents: [{
          documentId: "doc",
          kind: "converter",
          schemaVersion: 1,
          payload: { source: "B" },
          inputRevisionIds: [],
          resourceRefs: [],
          requiredCapabilities: ["converter.v1"],
        }],
      }),
    );
    expect(
      useProjectSessionStore.getState().commitSavedSnapshot(
        laterRevision,
        afterFork.changeSequence,
      ),
    ).toBe(true);
    expect(useProjectSessionStore.getState().activeProjectId).toBe(
      fork.manifest.projectId,
    );
  });
});

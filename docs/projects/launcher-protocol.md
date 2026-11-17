# Project-open protocol 1

Launcher reads only the `.lum` manifest summary. It accepts an installed runtime when the packaged marker supports the container/project schema and at least one document kind. A subset is labelled limited. It never takes an executable path or command from the project.

The fixed invocation is:

```text
runtime --open-project <absolute .lum path> --project-request-id <generated ID>
```

The body queues startup and second-instance requests. State is `received` → `awaiting-user` / `opening` → `opened`, `limited`, `failed` or `cancelled`. Readiness releases the queue but does not acknowledge restoration. A terminal successful receipt is sent only after the editor transaction commits. Save/discard/cancel belongs to the body's current project.

Managed installations write atomic JSON receipts under shared user data at `projects/open-requests/<requestId>.json` with `protocol: 1`, `requestId`, `state` and `runtimeKey`. Launcher accepts only the matching request and runtime. It also detects an exited runtime instead of polling indefinitely. Pending delivery and request maps are bounded.

The body stores path-indexed recent entries in shared `projects/catalog.json`. Launcher uses the opaque `fileEntryId` to select an entry, then rereads the file and installed capabilities. Reopening a different copy does not silently change another entry's save target.

Distribution includes `project-capabilities.v1.json` only when the frozen source has the real project broker and a valid marker. Standalone Electron owns `.lum` association; managed runtimes leave association to Launcher. Older bodies without project support receive no marker. The final Windows/macOS archive check verifies the exact marker bytes against source.

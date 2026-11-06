// UI primitives describe gesture boundaries without importing an application store.
let gesture: symbol | null = null;
export function currentDocumentGesture() { return gesture; }
export function beginDocumentGesture(): () => void {
  const own = Symbol("document gesture");
  gesture = own;
  return () => { if (gesture === own) gesture = null; };
}

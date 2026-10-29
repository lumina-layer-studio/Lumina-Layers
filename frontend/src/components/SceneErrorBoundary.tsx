import { Component, type ReactNode } from "react";
import { markSceneErrorHandled } from "../utils/handledSceneErrors";

/** Keeps optional scene assets from taking down the renderer that owns them. */
export default class SceneErrorBoundary extends Component<{
  children: ReactNode;
  fallback: ReactNode;
  onError: (error: Error) => void;
}, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(error: Error) {
    // Mark before the renderer reports its caught error globally. The local
    // recovery UI and onError diagnostic already handle this exact instance.
    markSceneErrorHandled(error);
    return { failed: true };
  }

  componentDidCatch(error: Error) {
    this.props.onError(error);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

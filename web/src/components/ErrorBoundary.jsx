import React from "react";

// Catches any render/runtime error in the React tree so a single component crash
// shows a recovery screen instead of a blank white page (common "vibe-coded" gap).
export default class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error, info) {
    // Keep details in the console for debugging; never surface internals to the user.
    console.error("Unhandled UI error:", error, info);
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div style={{ maxWidth: 460, margin: "12vh auto", padding: 24, textAlign: "center",
                    fontFamily: "system-ui, sans-serif", color: "#e8e4da" }}>
        <h2 style={{ marginBottom: 8 }}>Something went wrong</h2>
        <p style={{ opacity: 0.8, marginBottom: 20 }}>
          The page hit an unexpected error. Reloading usually fixes it. If it keeps happening,
          please let us know via the feedback button.
        </p>
        <button onClick={() => window.location.reload()}
                style={{ padding: "10px 20px", borderRadius: 8, border: "1px solid #b8924a",
                         background: "#b8924a", color: "#1a1206", fontWeight: 600, cursor: "pointer" }}>
          Reload
        </button>
      </div>
    );
  }
}

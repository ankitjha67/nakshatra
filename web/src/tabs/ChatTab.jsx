import React, { useState } from "react";
import { apiPost } from "../lib/api.js";

// Grounded chat — answers come only from the user's last cast chart's findings,
// metered on the token credit ledger. Balance updates flow up via onBalance.
export default function ChatTab({ lastBirth, onBalance }) {
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [chatId, setChatId] = useState(null);

  if (!lastBirth) {
    return (
      <div className="card">
        <p className="kicker">Chat</p>
        <h2 style={{ marginTop: 0 }}>Cast a chart first</h2>
        <p className="note">Chat is grounded in your computed chart. Open Natal or Maha-Kundali, cast a
          reading, then return here to ask follow-ups about what your chart actually says.</p>
      </div>
    );
  }

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setErr(""); setInput(""); setBusy(true);
    const history = msgs.filter((m) => !m.error).map((m) => ({ role: m.role, text: m.text }));
    setMsgs((m) => [...m, { role: "user", text }]);
    try {
      const resp = await apiPost("/v1/chat", { birth: lastBirth, message: text, history, chat_id: chatId });
      setChatId(resp.chat_id);
      setMsgs((m) => [...m, { role: "assistant", text: resp.answer, tokens: resp.tokens_used }]);
      onBalance && onBalance(resp.balance);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <p className="note" style={{ marginTop: 0, marginBottom: 16 }}>
        Grounded in your last cast chart — each turn is metered in tokens against your balance.
      </p>
      <div className="chat">
        {msgs.length === 0 && (
          <p className="note">Ask a question about your chart — e.g. “What does my chart say about career?”</p>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <p>{m.text}</p>
            {m.role === "assistant" && m.tokens != null && (
              <span className="chat-meta">{m.tokens.toLocaleString()} tokens</span>
            )}
          </div>
        ))}
        {busy && <div className="msg assistant"><p className="loader">Consulting your chart…</p></div>}
      </div>
      <p className="err">{err}</p>
      <div className="chat-input">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") send(); }}
          placeholder="Ask about your chart…"
          disabled={busy}
        />
        <button onClick={send} disabled={busy || !input.trim()}>Send</button>
      </div>
    </div>
  );
}

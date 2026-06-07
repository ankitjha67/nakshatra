import React, { useState } from "react";
import { auth } from "../lib/firebase.js";
import { GoogleAuthProvider, signInWithPopup, signInWithEmailAndPassword, createUserWithEmailAndPassword } from "firebase/auth";

export default function SignIn() {
  const [email, setEmail] = useState(""); const [pw, setPw] = useState(""); const [err, setErr] = useState("");
  const google = async () => { setErr(""); try { await signInWithPopup(auth, new GoogleAuthProvider()); } catch (e) { setErr(friendly(e)); } };
  const emailAuth = (fn) => async () => { setErr(""); if (!email || !pw) return setErr("Enter an email and password."); try { await fn(auth, email, pw); } catch (e) { setErr(friendly(e)); } };
  return (
    <div className="card">
      <p className="kicker">Step one · sign in</p>
      <button className="gsi" onClick={google}>Sign in with Google</button>
      <div className="grid" style={{ marginTop: 18 }}>
        <div><label className="fld">Email</label><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" /></div>
        <div><label className="fld">Password</label><input type="password" value={pw} onChange={(e) => setPw(e.target.value)} /></div>
      </div>
      <div className="actions">
        <button onClick={emailAuth(signInWithEmailAndPassword)}>Sign in</button>
        <button className="ghost" onClick={emailAuth(createUserWithEmailAndPassword)}>Create account</button>
      </div>
      <p className="err">{err}</p>
    </div>
  );
}
function friendly(e) {
  const c = (e && e.code) || "";
  if (c.includes("invalid-credential") || c.includes("wrong-password") || c.includes("user-not-found")) return "Email or password is incorrect.";
  if (c.includes("email-already-in-use")) return "That email already has an account — use Sign in.";
  if (c.includes("operation-not-allowed")) return "That sign-in method isn't enabled in Firebase.";
  return (e && e.message) || "Sign-in failed.";
}

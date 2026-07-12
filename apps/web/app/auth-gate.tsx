"use client";

import { FormEvent, useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import Dashboard from "./dashboard";
import { authConfigured, supabase } from "./lib/supabase";

function LoginScreen({onAuthenticated,restoreError}:{onAuthenticated:(session:Session)=>void;restoreError?:string}){
  const [email,setEmail]=useState("");
  const [password,setPassword]=useState("");
  const [error,setError]=useState("");
  const [submitting,setSubmitting]=useState(false);

  async function submit(event:FormEvent){
    event.preventDefault();
    if(!supabase)return;
    setSubmitting(true); setError("");
    const {data,error:signInError}=await supabase.auth.signInWithPassword({email:email.trim(),password});
    if(signInError||!data.session){
      setError("Email or password is incorrect.");
      setSubmitting(false);
      return;
    }
    onAuthenticated(data.session);
  }

  return <main className="login-shell">
    <section className="login-brand">
      <div className="login-logo">V</div>
      <span>VARIANZ</span>
      <h1>Operational intelligence for controlled-environment agriculture.</h1>
      <p>Detect deviations, quantify operational impact and turn evidence into clear operator action.</p>
      <div className="login-proof"><b>ENERGY & RESOURCES</b><b>OPERATIONAL CLIMATE</b><b>VARIANZ AI</b></div>
    </section>
    <section className="login-card">
      <span>PRIVATE DEMO</span>
      <h2>Sign in to Varianz</h2>
      <p>Use the demo credentials provided by the Varianz team.</p>
      {restoreError?<div className="login-error" role="alert">{restoreError}</div>:null}
      {!authConfigured?<div className="login-error">Authentication is not configured for this deployment.</div>:null}
      <form onSubmit={submit}>
        <label>Email<input autoComplete="username" type="email" required value={email} onChange={e=>setEmail(e.target.value)} placeholder="name@company.com"/></label>
        <label>Password<input autoComplete="current-password" type="password" required value={password} onChange={e=>setPassword(e.target.value)} placeholder="••••••••"/></label>
        {error?<div className="login-error" role="alert">{error}</div>:null}
        <button className="primary" disabled={!authConfigured||submitting}>{submitting?"Signing in…":"Sign in"}</button>
      </form>
      <small>Decision support only · No physical equipment control</small>
    </section>
  </main>
}

export default function AuthGate(){
  const [session,setSession]=useState<Session|null>(null);
  const [loading,setLoading]=useState(true);
  const [restoreError,setRestoreError]=useState("");

  useEffect(()=>{
    if(!supabase){setLoading(false);return;}
    let active=true;
    const timeout=new Promise<never>((_,reject)=>setTimeout(()=>reject(new Error("session_restore_timeout")),8000));
    Promise.race([supabase.auth.getSession(),timeout])
      .then(result=>{if(active){setSession(result.data.session);setRestoreError("")}})
      .catch(()=>{if(active){setSession(null);setRestoreError("The secure session could not be restored. Please sign in again.")}})
      .finally(()=>{if(active)setLoading(false)});
    const {data:{subscription}}=supabase.auth.onAuthStateChange((_event,next)=>{
      if(!active)return;
      setSession(next);setRestoreError("");setLoading(false);
    });
    return()=>{active=false;subscription.unsubscribe()};
  },[]);

  async function signOut(){
    if(supabase)await supabase.auth.signOut({scope:"local"});
    setSession(null);
  }

  if(loading)return <main className="auth-loading"><span/>Restoring secure session…</main>;
  if(!session)return <LoginScreen onAuthenticated={setSession} restoreError={restoreError}/>;
  return <Dashboard accessToken={session.access_token} userEmail={session.user.email||"Demo user"} onSignOut={signOut}/>;
}

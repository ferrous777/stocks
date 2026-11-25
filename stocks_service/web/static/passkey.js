// Passkey (WebAuthn) helpers for the sign-in and Security pages.
(function () {
  "use strict";
  function toBytes(s) {
    var b = atob(s.replace(/-/g, "+").replace(/_/g, "/")), out = new Uint8Array(b.length);
    for (var i = 0; i < b.length; i++) out[i] = b.charCodeAt(i);
    return out;
  }
  function toText(buf) {
    var s = "";
    new Uint8Array(buf).forEach(function (c) { s += String.fromCharCode(c); });
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  async function post(url, body) {
    var r = await fetch(url, { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    if (r.redirected) { location.assign("/login"); throw new Error("Signed out; sign in again."); }
    var data = await r.json().catch(function () { return {}; });
    if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request failed (" + r.status + ").");
    return data;
  }
  function credentialJson(c) {
    var r = c.response, out = { id: c.id, rawId: toText(c.rawId), type: c.type,
      clientExtensionResults: {}, response: { clientDataJSON: toText(r.clientDataJSON) } };
    if (c.authenticatorAttachment) out.authenticatorAttachment = c.authenticatorAttachment;
    if (r.attestationObject) {
      out.response.attestationObject = toText(r.attestationObject);
      if (r.getTransports) out.response.transports = r.getTransports();
    } else {
      out.response.authenticatorData = toText(r.authenticatorData);
      out.response.signature = toText(r.signature);
      if (r.userHandle) out.response.userHandle = toText(r.userHandle);
    }
    return out;
  }
  async function signIn() {
    var o = await post("/login/passkey/options");
    o.challenge = toBytes(o.challenge);
    var c = await navigator.credentials.get({ publicKey: o });
    await post("/login/passkey", { credential: credentialJson(c) });
    location.assign("/");
  }
  async function add(name) {
    var o = await post("/security/passkeys/options");
    o.challenge = toBytes(o.challenge);
    o.user.id = toBytes(o.user.id);
    (o.excludeCredentials || []).forEach(function (x) { x.id = toBytes(x.id); });
    var c = await navigator.credentials.create({ publicKey: o });
    await post("/security/passkeys", { credential: credentialJson(c), name: name });
    location.assign("/security?added=1");
  }
  function message(e) {
    if (e.name === "NotAllowedError") return "Cancelled, or no passkey for this site on this device.";
    if (e.name === "InvalidStateError") return "This device already has a passkey for this site.";
    return e.message || String(e);
  }
  function bind(id, event, run) {
    var el = document.getElementById(id), err = document.getElementById("passkey-error");
    if (!el) return;
    if (!window.PublicKeyCredential) { err.textContent = "This browser does not support passkeys."; err.hidden = false; return; }
    el.addEventListener(event, function (ev) {
      ev.preventDefault();
      err.hidden = true;
      run(el).catch(function (e) { err.textContent = message(e); err.hidden = false; });
    });
  }
  bind("passkey-signin", "click", signIn);
  bind("passkey-add", "submit", function (form) { return add(form.elements.name.value); });
})();

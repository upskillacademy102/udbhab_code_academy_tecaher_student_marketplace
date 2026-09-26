/**
 * Shared Jitsi Meet embed for the server-rendered (Alpine) pages - the
 * teacher's onboarding-call join and the reporter's bug-call join. The React
 * side has its own equivalent (frontend/src/routes/admin/support/JitsiCallPanel.tsx).
 *
 * meet.jit.si's external API is only fetched the first time someone actually
 * joins a call, never on ordinary page loads.
 */
(function () {
  const SRC = "https://meet.jit.si/external_api.js";
  let loading = null;

  function load() {
    if (window.JitsiMeetExternalAPI) return Promise.resolve();
    if (loading) return loading;
    loading = new Promise(function (resolve, reject) {
      const s = document.createElement("script");
      s.src = SRC;
      s.async = true;
      s.onload = function () { resolve(); };
      s.onerror = function () {
        loading = null;
        reject(new Error("Couldn't load the video-call library."));
      };
      document.head.appendChild(s);
    });
    return loading;
  }

  /**
   * Embed a call in `parentNode`. Resolves to the Jitsi API instance (call
   * `.dispose()` to leave). `onEnd` fires when the local user leaves.
   */
  async function embed(parentNode, roomName, opts) {
    opts = opts || {};
    await load();
    const api = new window.JitsiMeetExternalAPI("meet.jit.si", {
      roomName: roomName,
      parentNode: parentNode,
      width: "100%",
      height: opts.height || 420,
      userInfo: opts.displayName ? { displayName: opts.displayName } : undefined,
      configOverwrite: { prejoinPageEnabled: false },
    });
    if (opts.onEnd) {
      api.addListener("videoConferenceLeft", opts.onEnd);
      api.addListener("readyToClose", opts.onEnd);
    }
    return api;
  }

  window.tmJitsi = { load: load, embed: embed };
})();

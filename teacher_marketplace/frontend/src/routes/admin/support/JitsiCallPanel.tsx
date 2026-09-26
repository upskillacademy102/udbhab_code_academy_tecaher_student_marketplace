import { useEffect, useRef, useState } from "react";

const SCRIPT_SRC = "https://meet.jit.si/external_api.js";
let scriptPromise: Promise<void> | null = null;

function loadJitsiScript(): Promise<void> {
  if (scriptPromise) return scriptPromise;
  scriptPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${SCRIPT_SRC}"]`);
    if (existing) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = SCRIPT_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Couldn't load the video-call library."));
    document.head.appendChild(script);
  });
  return scriptPromise;
}

interface JitsiCallPanelProps {
  /** Unique room name - both sides must pass the same string to land in the same call. */
  roomName: string;
  /** Display name shown to the other participant. */
  displayName?: string;
  /** Fired once, when the local user leaves/the call ends. */
  onCallEnd?: () => void;
}

/**
 * Embeds a Jitsi Meet video call (meet.jit.si, no account/backend infra
 * needed) in a room identified by `roomName`. Shared by the onboarding-call
 * and bug-report-call queues - both just need "join this named room" and
 * "tell me when the call ends."
 */
export function JitsiCallPanel({ roomName, displayName, onCallEnd }: JitsiCallPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const apiRef = useRef<unknown>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let disposed = false;

    loadJitsiScript()
      .then(() => {
        if (disposed || !containerRef.current) return;
        const JitsiMeetExternalAPI = (window as unknown as { JitsiMeetExternalAPI: new (domain: string, opts: Record<string, unknown>) => unknown }).JitsiMeetExternalAPI;
        const api = new JitsiMeetExternalAPI("meet.jit.si", {
          roomName,
          parentNode: containerRef.current,
          width: "100%",
          height: 480,
          userInfo: displayName ? { displayName } : undefined,
          configOverwrite: { prejoinPageEnabled: false },
        }) as { addListener: (event: string, cb: () => void) => void; dispose: () => void };
        apiRef.current = api;
        api.addListener("videoConferenceLeft", () => {
          onCallEnd?.();
        });
        api.addListener("readyToClose", () => {
          onCallEnd?.();
        });
      })
      .catch((err: Error) => setError(err.message));

    return () => {
      disposed = true;
      const api = apiRef.current as { dispose?: () => void } | null;
      api?.dispose?.();
      apiRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomName]);

  if (error) {
    return <div className="u-alert u-alert-error">{error}</div>;
  }

  return <div ref={containerRef} className="overflow-hidden rounded-xl bg-ink-900" />;
}

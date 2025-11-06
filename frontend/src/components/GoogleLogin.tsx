import { useEffect, useRef } from "react";
import { GOOGLE_CLIENT_ID, setIdToken } from "../lib/auth";

declare global {
  interface Window { google: any }
}

export default function GoogleLogin({ onSignedIn }: { onSignedIn?: () => void }) {
  const btnRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onLoad = () => {
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (resp: any) => {
          const idt = resp?.credential;
          if (idt) {
            setIdToken(idt);
            onSignedIn?.();
          }
        },
        auto_select: false,
      });
      if (btnRef.current) {
        window.google.accounts.id.renderButton(btnRef.current, { theme: "outline", size: "large" });
      }

    };
    if ((window as any).google?.accounts?.id) onLoad();
    else {
      const i = setInterval(() => {
        if ((window as any).google?.accounts?.id) { clearInterval(i); onLoad(); }
      }, 100);
      return () => clearInterval(i);
    }
  }, [onSignedIn]);

  return <div ref={btnRef} />;
}

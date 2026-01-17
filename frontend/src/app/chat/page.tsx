import { Suspense } from "react";
import ChatClient from "./ChatClient";

export default function Page() {
  return (
    <Suspense fallback={<div style={{ padding: 16 }}>Loading…</div>}>
      <ChatClient />
    </Suspense>
  );
}

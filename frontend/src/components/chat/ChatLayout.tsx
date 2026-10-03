import Sidebar from "./Sidebar";
import ChatPanel from "./ChatPanel";

export default function ChatLayout() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />

      {/* min-w-0 允许该区域收缩 */}
      <main className="flex-1 min-w-0">
        <ChatPanel />
      </main>
    </div>
  );
}

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8 bg-zinc-950 text-zinc-100">
      <div className="max-w-md w-full text-center space-y-4">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium bg-zinc-800/80 text-zinc-300 border border-zinc-700">
          <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          Environment Ready
        </div>
        <h1 className="text-3xl font-bold tracking-tight text-white">
          AEGIS-Flow
        </h1>
        <p className="text-sm text-zinc-400">
          Temporal Fraud-Flow Intervention Engine
        </p>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4 text-xs text-zinc-400">
          Frontend environment initialized. Awaiting dashboard implementation.
        </div>
      </div>
    </main>
  );
}

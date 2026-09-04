import Dashboard from "@/components/DigitalShelfDashboard";

export default function Home() {
  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 p-6 md:p-10">
      <div className="max-w-7xl mx-auto space-y-8">
        <Dashboard />
      </div>
    </main>
  );
}
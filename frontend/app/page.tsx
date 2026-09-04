"use client";

import Dashboard from "../src/components/DigitalShelfDashboard";

export default function Home() {
  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 p-6 md:p-10">
      <div className="max-w-7xl mx-auto space-y-8">
        <header className="border-b border-slate-800 pb-5">
          <h1 className="text-3xl font-extrabold tracking-tight text-white">
            Digital Shelf Analytics
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Auditoría multitienda en tiempo real: visibilidad, precios y disponibilidad en retail ecommerce.
          </p>
        </header>

        <Dashboard />
      </div>
    </main>
  );
}
"use client";

import React, { useEffect, useState } from "react";
import { Activity, Play, Plus, RefreshCw, ShoppingCart, Store } from "lucide-react";

interface Retailer {
  id: string;
  code: string;
  name: string;
  base_url: string;
  is_active: boolean;
}

interface MonitoringConfig {
  id: string;
  name: string;
  retailer_id: string;
  search_keyword: string;
  frequency_hours: number;
  is_active: boolean;
}

export default function Dashboard() {
  const [retailers, setRetailers] = useState<Retailer[]>([]);
  const [configs, setConfigs] = useState<MonitoringConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

  const fetchData = async () => {
    try {
      const [resRetailers, resConfigs] = await Promise.all([
        fetch(`${API_URL}/retailers/`),
        fetch(`${API_URL}/configs/`)
      ]);
      setRetailers(await resRetailers.json());
      setConfigs(await resConfigs.json());
    } catch (err) {
      console.error("Error al conectar con el backend", err);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const triggerMonitoring = async () => {
    setLoading(true);
    try {
      await fetch(`${API_URL}/trigger-now`, { method: "POST" });
      alert("🚀 ¡Monitoreo ejecutado en tiempo real!");
    } catch (err) {
      alert("❌ Error ejecutando el monitoreo.");
    } finally {
      setLoading(false);
    }
  };

  const createConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!keyword) return;
    const exito = retailers.find((r) => r.code === "exito");
    if (!exito) return;

    try {
      await fetch(`${API_URL}/configs/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: `Busqueda: ${keyword}`,
          retailer_id: exito.id,
          search_keyword: keyword,
          frequency_hours: 6
        })
      });
      setKeyword("");
      fetchData();
    } catch (err) {
      console.error("Error al guardar la configuración", err);
    }
  };

  return (
    <main className="min-h-screen bg-slate-900 text-slate-100 p-8 font-sans">
      <header className="flex justify-between items-center mb-10 pb-4 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <Activity className="text-emerald-400 w-8 h-8" />
          <h1 className="text-2xl font-bold tracking-tight">Digital Shelf Monitoring</h1>
        </div>
        <button
          onClick={triggerMonitoring}
          disabled={loading}
          className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold px-4 py-2 rounded-lg transition-all disabled:opacity-50"
        >
          {loading ? <RefreshCw className="animate-spin w-4 h-4" /> : <Play className="w-4 h-4" />}
          Ejecutar Monitoreo Ahora
        </button>
      </header>

      {/* Grid KPI Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-10">
        <div className="bg-slate-800 p-6 rounded-xl border border-slate-700 flex items-center gap-4">
          <Store className="text-blue-400 w-10 h-10" />
          <div>
            <p className="text-sm text-slate-400">Retailers Activos</p>
            <p className="text-2xl font-bold">{retailers.length}</p>
          </div>
        </div>
        <div className="bg-slate-800 p-6 rounded-xl border border-slate-700 flex items-center gap-4">
          <ShoppingCart className="text-purple-400 w-10 h-10" />
          <div>
            <p className="text-sm text-slate-400">Configuraciones de Búsqueda</p>
            <p className="text-2xl font-bold">{configs.length}</p>
          </div>
        </div>
        <div className="bg-slate-800 p-6 rounded-xl border border-slate-700 flex items-center gap-4">
          <Activity className="text-emerald-400 w-10 h-10" />
          <div>
            <p className="text-sm text-slate-400">Estado del Sistema</p>
            <p className="text-2xl font-bold text-emerald-400">ONLINE</p>
          </div>
        </div>
      </div>

      {/* Form & List Container */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <div className="bg-slate-800 p-6 rounded-xl border border-slate-700">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Plus className="w-5 h-5 text-emerald-400" /> Crear Nueva Búsqueda
          </h2>
          <form onSubmit={createConfig} className="flex flex-col gap-4">
            <div>
              <label className="block text-sm text-slate-400 mb-1">Palabra Clave (Keyword)</label>
              <input
                type="text"
                placeholder="Ej. Galletas Ducales, Chocolates..."
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:border-emerald-500"
              />
            </div>
            <button
              type="submit"
              className="bg-blue-600 hover:bg-blue-500 text-white font-medium py-2 rounded-lg transition-all"
            >
              Guardar Configuración
            </button>
          </form>
        </div>

        <div className="bg-slate-800 p-6 rounded-xl border border-slate-700">
          <h2 className="text-lg font-semibold mb-4">Monitoreos Programados</h2>
          <div className="flex flex-col gap-3">
            {configs.map((cfg) => (
              <div key={cfg.id} className="bg-slate-900 p-4 rounded-lg flex justify-between items-center border border-slate-700/50">
                <div>
                  <p className="font-medium text-slate-200">{cfg.name}</p>
                  <p className="text-xs text-slate-500">Frecuencia: cada {cfg.frequency_hours} horas</p>
                </div>
                <span className="text-xs bg-emerald-500/10 text-emerald-400 px-3 py-1 rounded-full border border-emerald-500/20">
                  Activo
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
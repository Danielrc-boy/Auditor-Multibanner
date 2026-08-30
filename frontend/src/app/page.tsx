"use client";

import React, { useEffect, useState, useCallback } from "react";
import { 
  Activity, 
  Play, 
  Plus, 
  RefreshCw, 
  ShoppingCart, 
  Store, 
  Download, 
  Search, 
  Filter, 
  CheckCircle, 
  XCircle, 
  TrendingDown,
  Trash2
} from "lucide-react";

// Types
interface Retailer {
  id: string;
  code: string;
  name: string;
  base_url?: string;
  is_active: boolean;
}

interface MonitoringConfig {
  id: string;
  search_term: string;
  name?: string;
  retailer_id?: string;
  frequency_hours?: number;
  is_active?: boolean;
}

interface ScraperResult {
  id: number;
  retailer: string;
  search_term: string;
  product_name: string;
  position: number;
  price: number;
  discount_price: number | null;
  is_available: boolean;
  captured_at: string;
}

export default function Dashboard() {
  const [retailers, setRetailers] = useState<Retailer[]>([]);
  const [configs, setConfigs] = useState<MonitoringConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [selectedRetailerId, setSelectedRetailerId] = useState("");

  // Estados de la Tabla de Resultados y Filtros
  const [results, setResults] = useState<ScraperResult[]>([]);
  const [loadingResults, setLoadingResults] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [errorResults, setErrorResults] = useState<string | null>(null);

  const [filterRetailer, setFilterRetailer] = useState("");
  const [filterSearchTerm, setFilterSearchTerm] = useState("");
  const [filterDateFrom, setFilterDateFrom] = useState("");
  const [filterDateTo, setFilterDateTo] = useState("");

  const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://auditor-multibanner-production.up.railway.app";

  const fetchData = async () => {
    try {
      const [resRetailers, resConfigs] = await Promise.all([
        fetch(`${API_URL}/retailers`),
        fetch(`${API_URL}/configs`)
      ]);
      
      const dataRetailers: Retailer[] = await resRetailers.json();
      const dataConfigs: MonitoringConfig[] = await resConfigs.json();

      setRetailers(dataRetailers);
      setConfigs(dataConfigs);

      if (dataRetailers.length > 0 && !selectedRetailerId) {
        setSelectedRetailerId(dataRetailers[0].id);
      }
    } catch (err) {
      console.error("Error al conectar con el backend:", err);
    }
  };

  const loadResults = useCallback(async () => {
    setLoadingResults(true);
    setErrorResults(null);
    try {
      const queryParams = new URLSearchParams();
      if (filterRetailer) queryParams.append("retailer", filterRetailer);
      if (filterSearchTerm) queryParams.append("search_term", filterSearchTerm);
      if (filterDateFrom) queryParams.append("date_from", new Date(filterDateFrom).toISOString());
      if (filterDateTo) queryParams.append("date_to", new Date(filterDateTo).toISOString());
      queryParams.append("limit", "200");

      const res = await fetch(`${API_URL}/results?${queryParams.toString()}`);
      if (!res.ok) throw new Error("Error al obtener los resultados.");
      const data = await res.json();
      setResults(data);
    } catch (err: any) {
      setErrorResults(err.message || "Error al cargar los datos");
    } finally {
      setLoadingResults(false);
    }
  }, [API_URL, filterRetailer, filterSearchTerm, filterDateFrom, filterDateTo]);

  useEffect(() => {
    fetchData();
    loadResults();
  }, []);

  const triggerMonitoring = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/trigger-now`, { method: "POST" });
      if (!res.ok) throw new Error("Fallo en la respuesta del servidor");
      alert("🚀 ¡Monitoreo ejecutado en tiempo real!");
      loadResults();
    } catch (err) {
      console.error(err);
      alert("❌ Error ejecutando el monitoreo.");
    } finally {
      setLoading(false);
    }
  };

  const createConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!keyword) {
      alert("Por favor ingresa una palabra clave.");
      return;
    }

    try {
      const res = await fetch(`${API_URL}/configs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          search_term: keyword
        })
      });

      if (!res.ok) throw new Error("Error al guardar en la base de datos");

      setKeyword("");
      fetchData();
    } catch (err) {
      console.error("Error al guardar la configuración:", err);
      alert("❌ No se pudo guardar la configuración.");
    }
  };

  const toggleConfigStatus = async (id: string) => {
    try {
      const res = await fetch(`${API_URL}/configs/${id}/toggle`, {
        method: "PATCH",
      });
      if (!res.ok) throw new Error("Error al cambiar el estado");
      fetchData();
    } catch (err) {
      console.error("Error toggling status:", err);
      alert("❌ No se pudo cambiar el estado de la búsqueda.");
    }
  };

  const deleteConfig = async (id: string) => {
    if (!confirm("¿Estás seguro de que deseas eliminar esta búsqueda?")) return;
    try {
      const res = await fetch(`${API_URL}/configs/${id}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Error al eliminar");
      fetchData();
    } catch (err) {
      console.error("Error deleting config:", err);
      alert("❌ No se pudo eliminar la configuración.");
    }
  };

  const handleExportExcel = async () => {
    setExporting(true);
    try {
      const queryParams = new URLSearchParams();
      if (filterRetailer) queryParams.append("retailer", filterRetailer);
      if (filterSearchTerm) queryParams.append("search_term", filterSearchTerm);
      if (filterDateFrom) queryParams.append("date_from", new Date(filterDateFrom).toISOString());
      if (filterDateTo) queryParams.append("date_to", new Date(filterDateTo).toISOString());

      const res = await fetch(`${API_URL}/export?${queryParams.toString()}`);
      if (!res.ok) throw new Error("No fue posible generar el reporte Excel.");

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `digital_shelf_export_${new Date().toISOString().slice(0, 10)}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      alert("❌ Error al exportar: " + err.message);
    } finally {
      setExporting(false);
    }
  };

  const formatCurrency = (val: number) => {
    return new Intl.NumberFormat("es-CO", {
      style: "currency",
      currency: "COP",
      maximumFractionDigits: 0,
    }).format(val);
  };

  const totalItems = results.length;
  const availableItems = results.filter((r) => r.is_available).length;
  const outOfStockRate = totalItems > 0 ? (((totalItems - availableItems) / totalItems) * 100).toFixed(1) : "0";
  const withDiscount = results.filter((r) => r.discount_price && r.discount_price < r.price).length;

  return (
    <main className="min-h-screen bg-slate-900 text-slate-100 p-8 font-sans space-y-10">
      <header className="flex justify-between items-center pb-4 border-b border-slate-800">
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
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
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
              <label className="block text-sm text-slate-400 mb-1">Retailer / Comercio</label>
              <select
                value={selectedRetailerId}
                onChange={(e) => setSelectedRetailerId(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:border-emerald-500"
              >
                {retailers.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name} ({r.code})
                  </option>
                ))}
              </select>
            </div>

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
            {configs.length === 0 ? (
              <p className="text-sm text-slate-500">No hay búsquedas configuradas.</p>
            ) : (
              configs.map((cfg) => (
                <div key={cfg.id} className="bg-slate-900 p-4 rounded-lg flex justify-between items-center border border-slate-700/50">
                  <div>
                    <p className="font-medium text-slate-200">{cfg.name || `Búsqueda: ${cfg.search_term}`}</p>
                    <p className="text-xs text-slate-500">Frecuencia: cada {cfg.frequency_hours || 6} horas</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => toggleConfigStatus(cfg.id)}
                      className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                        cfg.is_active !== false
                          ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20 hover:bg-emerald-500/20"
                          : "bg-rose-500/10 text-rose-400 border-rose-500/20 hover:bg-rose-500/20"
                      }`}
                    >
                      {cfg.is_active !== false ? "Activo" : "Inactivo"}
                    </button>
                    <button
                      onClick={() => deleteConfig(cfg.id)}
                      className="text-slate-500 hover:text-rose-400 transition-colors p-1"
                      title="Eliminar búsqueda"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* --- SECCIÓN ANALÍTICA: TABLA Y EXPORTACIÓN --- */}
      <section className="space-y-6 pt-6 border-t border-slate-800">
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 shadow-lg">
          <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-4">
            <div className="flex items-center gap-2">
              <Filter className="w-5 h-5 text-emerald-400" />
              <h2 className="text-xl font-bold tracking-tight">Filtros de Anaquel Digital</h2>
            </div>
            <div className="flex items-center gap-3 w-full md:w-auto">
              <button
                onClick={loadResults}
                disabled={loadingResults}
                className="flex items-center justify-center gap-2 px-4 py-2 bg-slate-900 hover:bg-slate-700 text-slate-200 rounded-lg text-sm font-medium transition-colors border border-slate-700 disabled:opacity-50"
              >
                <RefreshCw className={`w-4 h-4 ${loadingResults ? "animate-spin" : ""}`} />
                Filtrar / Actualizar
              </button>
              <button
                onClick={handleExportExcel}
                disabled={exporting || results.length === 0}
                className="flex items-center justify-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-sm font-semibold transition-colors shadow-lg shadow-emerald-950/40 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Download className="w-4 h-4" />
                {exporting ? "Generando..." : "Exportar Excel (.xlsx)"}
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div>
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Retailer</label>
              <select
                value={filterRetailer}
                onChange={(e) => setFilterRetailer(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                <option value="">Todos los Retailers</option>
                <option value="Exito">Éxito</option>
                <option value="Carulla">Carulla</option>
                <option value="Farmatodo">Farmatodo</option>
                <option value="Rappi">Rappi</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Búsqueda / Keyword</label>
              <div className="relative">
                <input
                  type="text"
                  placeholder="Ej. Nosotras, Cuidado Intimo..."
                  value={filterSearchTerm}
                  onChange={(e) => setFilterSearchTerm(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
                <Search className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" />
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Fecha Desde</label>
              <input
                type="date"
                value={filterDateFrom}
                onChange={(e) => setFilterDateFrom(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Fecha Hasta</label>
              <input
                type="date"
                value={filterDateTo}
                onChange={(e) => setFilterDateTo(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>
          </div>
        </div>

        {/* KPIs dinámicos sobre resultados */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="bg-slate-800 border border-slate-700 p-4 rounded-xl flex items-center gap-4">
            <div className="p-3 bg-emerald-500/10 text-emerald-400 rounded-lg">
              <Store className="w-6 h-6" />
            </div>
            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase">Capturas Mostradas</p>
              <p className="text-2xl font-bold">{totalItems}</p>
            </div>
          </div>

          <div className="bg-slate-800 border border-slate-700 p-4 rounded-xl flex items-center gap-4">
            <div className="p-3 bg-rose-500/10 text-rose-400 rounded-lg">
              <XCircle className="w-6 h-6" />
            </div>
            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase">Tasa Agotados (OOS)</p>
              <p className="text-2xl font-bold">{outOfStockRate}%</p>
            </div>
          </div>

          <div className="bg-slate-800 border border-slate-700 p-4 rounded-xl flex items-center gap-4">
            <div className="p-3 bg-amber-500/10 text-amber-400 rounded-lg">
              <TrendingDown className="w-6 h-6" />
            </div>
            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase">Con Descuento</p>
              <p className="text-2xl font-bold">{withDiscount}</p>
            </div>
          </div>
        </div>

        {/* Tabla de Resultados en tiempo real */}
        <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden shadow-lg">
          <div className="p-4 border-b border-slate-700 flex justify-between items-center">
            <h3 className="font-bold text-slate-200">Resultados Extraídos (Anaquel Digital)</h3>
            {errorResults && <span className="text-xs text-rose-400">{errorResults}</span>}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="bg-slate-900 text-slate-400 text-xs uppercase font-semibold border-b border-slate-700">
                <tr>
                  <th className="px-4 py-3">Retailer</th>
                  <th className="px-4 py-3">Término</th>
                  <th className="px-4 py-3">Pos.</th>
                  <th className="px-4 py-3">Producto</th>
                  <th className="px-4 py-3">Precio Base</th>
                  <th className="px-4 py-3">Precio Final</th>
                  <th className="px-4 py-3">Estado</th>
                  <th className="px-4 py-3">Fecha</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/50">
                {loadingResults ? (
                  Array.from({ length: 4 }).map((_, i) => (
                    <tr key={i} className="animate-pulse">
                      <td colSpan={8} className="px-4 py-4">
                        <div className="h-4 bg-slate-700 rounded"></div>
                      </td>
                    </tr>
                  ))
                ) : results.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-slate-500">
                      No hay resultados capturados para los filtros seleccionados.
                    </td>
                  </tr>
                ) : (
                  results.map((row) => {
                    const hasDiscount = row.discount_price && row.discount_price < row.price;
                    const finalPrice = hasDiscount ? row.discount_price! : row.price;

                    return (
                      <tr key={row.id} className="hover:bg-slate-700/30 transition-colors">
                        <td className="px-4 py-3 font-medium text-slate-200">
                          <span className="px-2 py-1 bg-slate-900 rounded border border-slate-700 text-xs">
                            {row.retailer}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-400">{row.search_term}</td>
                        <td className="px-4 py-3 font-semibold text-emerald-400">#{row.position}</td>
                        <td className="px-4 py-3 max-w-xs truncate font-medium text-slate-100" title={row.product_name}>
                          {row.product_name}
                        </td>
                        <td className={`px-4 py-3 ${hasDiscount ? "line-through text-slate-500 text-xs" : ""}`}>
                          {formatCurrency(row.price)}
                        </td>
                        <td className="px-4 py-3 font-bold text-slate-100">
                          {formatCurrency(finalPrice)}
                          {hasDiscount && (
                            <span className="ml-2 text-[10px] bg-amber-500/20 text-amber-300 border border-amber-500/30 px-1.5 py-0.5 rounded">
                              Oferta
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          {row.is_available ? (
                            <span className="inline-flex items-center gap-1 text-xs text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20">
                              <CheckCircle className="w-3 h-3" /> Disponible
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-xs text-rose-400 bg-rose-500/10 px-2 py-0.5 rounded-full border border-rose-500/20">
                              <XCircle className="w-3 h-3" /> Agotado
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-400">
                          {new Date(row.captured_at).toLocaleString("es-CO", {
                            day: "2-digit",
                            month: "short",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </main>
  );
}
"use client";

import React, { useState, useEffect, useCallback } from "react";
import { 
  Download, 
  Search, 
  Filter, 
  RefreshCw, 
  CheckCircle, 
  XCircle, 
  TrendingDown, 
  Store 
} from "lucide-react";
import { fetchResults, downloadExcelExport, ScraperResult, FilterParams } from "../services/api";

export const DigitalShelfDashboard: React.FC = () => {
  const [results, setResults] = useState<ScraperResult[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [exporting, setExporting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Estados de Filtros
  const [retailer, setRetailer] = useState<string>("");
  const [searchTerm, setSearchTerm] = useState<string>("");
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const filters: FilterParams = {
        retailer: retailer || undefined,
        search_term: searchTerm || undefined,
        date_from: dateFrom ? new Date(dateFrom).toISOString() : undefined,
        date_to: dateTo ? new Date(dateTo).toISOString() : undefined,
        limit: 200,
      };
      const data = await fetchResults(filters);
      setResults(data);
    } catch (err: any) {
      setError(err.message || "Error al cargar datos");
    } finally {
      setLoading(false);
    }
  }, [retailer, searchTerm, dateFrom, dateTo]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleExport = async () => {
    setExporting(true);
    try {
      const filters: FilterParams = {
        retailer: retailer || undefined,
        search_term: searchTerm || undefined,
        date_from: dateFrom ? new Date(dateFrom).toISOString() : undefined,
        date_to: dateTo ? new Date(dateTo).toISOString() : undefined,
      };
      await downloadExcelExport(filters);
    } catch (err: any) {
      alert("Error al exportar a Excel: " + err.message);
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

  // KPIs calculados dinámicamente sobre los resultados visibles
  const totalItems = results.length;
  const availableItems = results.filter((r) => r.is_available).length;
  const outOfStockRate = totalItems > 0 ? (((totalItems - availableItems) / totalItems) * 100).toFixed(1) : "0";
  const withDiscount = results.filter((r) => r.discount_price && r.discount_price < r.price).length;

  return (
    <div className="w-full space-y-6 text-slate-100">
      {/* Panel Superior: Filtros & Exportación */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-4">
          <div className="flex items-center gap-2">
            <Filter className="w-5 h-5 text-emerald-400" />
            <h2 className="text-xl font-bold tracking-tight">Filtros de Auditoría</h2>
          </div>
          <div className="flex items-center gap-3 w-full md:w-auto">
            <button
              onClick={loadData}
              disabled={loading}
              className="flex items-center justify-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-sm font-medium transition-colors border border-slate-700 disabled:opacity-50"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
              Actualizar
            </button>
            <button
              onClick={handleExport}
              disabled={exporting || results.length === 0}
              className="flex items-center justify-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-sm font-semibold transition-colors shadow-lg shadow-emerald-950/40 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Download className="w-4 h-4" />
              {exporting ? "Generando..." : "Exportar Excel (.xlsx)"}
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Selector Retailer */}
          <div>
            <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Retailer</label>
            <select
              value={retailer}
              onChange={(e) => setRetailer(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              <option value="">Todos los Retailers</option>
              <option value="Exito">Éxito</option>
              <option value="Carulla">Carulla</option>
              <option value="Farmatodo">Farmatodo</option>
              <option value="Rappi">Rappi</option>
            </select>
          </div>

          {/* Término de Búsqueda */}
          <div>
            <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Búsqueda / Keyword</label>
            <div className="relative">
              <input
                type="text"
                placeholder="Ej. Nosotras, Cuidado Intimo..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-9 pr-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
              <Search className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" />
            </div>
          </div>

          {/* Fecha Desde */}
          <div>
            <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Fecha Desde</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>

          {/* Fecha Hasta */}
          <div>
            <label className="block text-xs font-semibold uppercase text-slate-400 mb-1">Fecha Hasta</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>
        </div>
      </div>

      {/* Tarjetas KPI */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-slate-900 border border-slate-800 p-4 rounded-xl flex items-center gap-4">
          <div className="p-3 bg-emerald-500/10 text-emerald-400 rounded-lg">
            <Store className="w-6 h-6" />
          </div>
          <div>
            <p className="text-xs font-semibold text-slate-400 uppercase">Capturas Mostradas</p>
            <p className="text-2xl font-bold">{totalItems}</p>
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 p-4 rounded-xl flex items-center gap-4">
          <div className="p-3 bg-rose-500/10 text-rose-400 rounded-lg">
            <XCircle className="w-6 h-6" />
          </div>
          <div>
            <p className="text-xs font-semibold text-slate-400 uppercase">Tasa Agotados (OOS)</p>
            <p className="text-2xl font-bold">{outOfStockRate}%</p>
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 p-4 rounded-xl flex items-center gap-4">
          <div className="p-3 bg-amber-500/10 text-amber-400 rounded-lg">
            <TrendingDown className="w-6 h-6" />
          </div>
          <div>
            <p className="text-xs font-semibold text-slate-400 uppercase">Con Descuento</p>
            <p className="text-2xl font-bold">{withDiscount}</p>
          </div>
        </div>
      </div>

      {/* Tabla de Resultados */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-lg">
        <div className="p-4 border-b border-slate-800 flex justify-between items-center">
          <h3 className="font-bold text-slate-200">Monitoreo de Anaquel Digital</h3>
          {error && <span className="text-xs text-rose-400">{error}</span>}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm text-slate-300">
            <thead className="bg-slate-950 text-slate-400 text-xs uppercase font-semibold border-b border-slate-800">
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
            <tbody className="divide-y divide-slate-800">
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="animate-pulse">
                    <td colSpan={8} className="px-4 py-4">
                      <div className="h-4 bg-slate-800 rounded"></div>
                    </td>
                  </tr>
                ))
              ) : results.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-slate-500">
                    No se encontraron registros de monitoreo para los filtros seleccionados.
                  </td>
                </tr>
              ) : (
                results.map((row) => {
                  const hasDiscount = row.discount_price && row.discount_price < row.price;
                  const finalPrice = hasDiscount ? row.discount_price! : row.price;

                  return (
                    <tr key={row.id} className="hover:bg-slate-800/50 transition-colors">
                      <td className="px-4 py-3 font-medium text-slate-200">
                        <span className="px-2 py-1 bg-slate-800 rounded border border-slate-700 text-xs">
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
    </div>
  );
};
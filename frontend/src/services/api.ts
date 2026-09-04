const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "https://auditor-multibanner-production.up.railway.app";

export interface ScraperResult {
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

export interface FilterParams {
  retailer?: string;
  search_term?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
}

export const fetchResults = async (filters: FilterParams = {}): Promise<ScraperResult[]> => {
  const queryParams = new URLSearchParams();

  if (filters.retailer) queryParams.append("retailer", filters.retailer);
  if (filters.search_term) queryParams.append("search_term", filters.search_term);
  if (filters.date_from) queryParams.append("date_from", filters.date_from);
  if (filters.date_to) queryParams.append("date_to", filters.date_to);
  if (filters.limit) queryParams.append("limit", filters.limit.toString());

  const response = await fetch(`${API_BASE_URL}/results?${queryParams.toString()}`);
  if (!response.ok) {
    throw new Error(`Error en la solicitud: ${response.statusText}`);
  }
  return response.json();
};

export const downloadExcelExport = async (filters: FilterParams = {}): Promise<void> => {
  const queryParams = new URLSearchParams();

  if (filters.retailer) queryParams.append("retailer", filters.retailer);
  if (filters.search_term) queryParams.append("search_term", filters.search_term);
  if (filters.date_from) queryParams.append("date_from", filters.date_from);
  if (filters.date_to) queryParams.append("date_to", filters.date_to);

  const response = await fetch(`${API_BASE_URL}/export?${queryParams.toString()}`);

  if (!response.ok) {
    throw new Error("No fue posible generar la exportación.");
  }

  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `digital_shelf_export_${new Date().toISOString().slice(0, 10)}.xlsx`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
};
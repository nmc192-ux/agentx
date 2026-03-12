"use client";

import { useEffect, useState } from "react";

const API_BASE = "http://localhost:8000";
const REFRESH_MS = 3000;

type ServiceItem = {
  service_id: string;
  service_type: string;
  agent_did: string;
  service_name: string;
};

async function fetchServices(): Promise<ServiceItem[]> {
  const response = await fetch(`${API_BASE}/dashboard/services`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error("Failed to fetch services");
  }

  return response.json();
}

export function ServiceList() {
  const [services, setServices] = useState<ServiceItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    const load = async () => {
      try {
        const nextServices = await fetchServices();
        if (!active) {
          return;
        }
        setServices(nextServices);
        setError(null);
      } catch {
        if (!active) {
          return;
        }
        setError("Services unavailable");
      }
    };

    void load();
    const timer = window.setInterval(() => {
      void load();
    }, REFRESH_MS);

    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="panel-kicker">Marketplace</p>
          <h2 className="panel-title">Services</h2>
        </div>
        <span className="status-chip">{services.length} listed</span>
      </div>

      {error ? <p className="panel-empty">{error}</p> : null}

      <div className="space-y-3 overflow-y-auto pr-1">
        {services.slice(0, 12).map((service) => (
          <article
            key={service.service_id}
            className="rounded-2xl border border-white/10 bg-white/5 p-4"
          >
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-slate-100">
                {service.service_type}
              </h3>
              <span className="rounded-full bg-amber-300/15 px-3 py-1 text-xs font-semibold text-amber-100">
                Active
              </span>
            </div>
            <p className="mt-2 text-sm text-slate-300">{service.service_name}</p>
            <p className="mt-3 text-xs text-slate-400">{service.agent_did}</p>
          </article>
        ))}

        {!error && services.length === 0 ? (
          <p className="panel-empty">No services published</p>
        ) : null}
      </div>
    </section>
  );
}

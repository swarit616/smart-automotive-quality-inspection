import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

export interface Async<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** Fetches on mount and whenever `deps` change; optionally polls. Aborts stale updates. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[], pollMs?: number): Async<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let alive = true;
    const run = async (initial: boolean) => {
      if (initial) setLoading(true);
      try {
        const d = await fnRef.current();
        if (alive) {
          setData(d);
          setError(null);
        }
      } catch (e) {
        if (alive) setError(e instanceof ApiError ? e.message : String(e));
      } finally {
        if (alive && initial) setLoading(false);
      }
    };
    void run(true);
    const id = pollMs ? window.setInterval(() => void run(false), pollMs) : undefined;
    return () => {
      alive = false;
      if (id) window.clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, pollMs]);

  return { data, error, loading, reload };
}

export function useHashRoute(defaultRoute: string): [string, (r: string) => void] {
  const read = () => window.location.hash.replace(/^#\/?/, "") || defaultRoute;
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => setRoute(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return [route, (r) => { window.location.hash = "/" + r; }];
}

export const fmtTime = (iso: string) => {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
};
export const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

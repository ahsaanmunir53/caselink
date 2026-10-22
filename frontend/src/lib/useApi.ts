import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api";

/** GET a path, keep the last good data while reloading (no flash), expose reload. */
export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const seq = useRef(0);

  const load = useCallback(() => {
    if (!path) return;
    const n = ++seq.current;
    setLoading(true);
    api.get<T>(path)
      .then((d) => {
        if (n === seq.current) {
          setData(d);
          setError(null);
        }
      })
      .catch((e: Error) => n === seq.current && setError(e.message))
      .finally(() => n === seq.current && setLoading(false));
  }, [path]);

  useEffect(() => {
    load();
  }, [load]);

  return { data, error, loading, reload: load, setData };
}

/** Run an action with a busy flag; errors go to the toast. */
export function useAction(toast: (m: string, tone?: "ok" | "bad") => void) {
  const [busy, setBusy] = useState<string | null>(null);
  const run = useCallback(async <R,>(name: string, fn: () => Promise<R>, done?: string): Promise<R | undefined> => {
    setBusy(name);
    try {
      const out = await fn();
      if (done) toast(done);
      return out;
    } catch (e) {
      toast((e as Error).message, "bad");
      return undefined;
    } finally {
      setBusy(null);
    }
  }, [toast]);
  return { busy, run };
}

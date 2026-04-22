import { useState, useEffect } from "react";
import { api, Suggestion } from "../lib/api";

interface UseSuggestionsResult {
  suggestions: Suggestion[];
  count: number;
  loading: boolean;
}

export function useSuggestions(pollIntervalMs = 300_000, paused = false): UseSuggestionsResult {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (paused) {
      setLoading(false);
      return;
    }

    let cancelled = false;

    async function poll() {
      try {
        const res = await api.getSuggestions();
        if (!cancelled) setSuggestions(res.suggestions);
      } catch {
        // Keep stale data; sidecar may not be reachable yet
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    poll();
    const id = setInterval(poll, pollIntervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [pollIntervalMs, paused]);

  return { suggestions, count: suggestions.length, loading };
}

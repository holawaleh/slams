import { useCallback, useEffect, useState } from "react";
import api from "./api";

// Fetches a paginated DRF list endpoint. Returns the rows plus helpers
// for searching, paging and reloading after a change.
export function useList(path, params = {}) {
  const [rows, setRows] = useState([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const key = JSON.stringify(params);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .get(path, { params: { page, ...JSON.parse(key) } })
      .then(({ data }) => {
        setRows(data.results ?? data);
        setCount(data.count ?? (data.results ?? data).length);
      })
      .catch(setError)
      .finally(() => setLoading(false));
  }, [path, page, key]);

  useEffect(load, [load]);

  // A changed filter should send you back to page one, or you can land
  // on an empty page that exists only for the previous search.
  useEffect(() => setPage(1), [key]);

  return { rows, count, page, setPage, loading, error, reload: load };
}

// Delays a value so typing in a search box does not fire a request per
// keystroke.
export function useDebounced(value, ms = 350) {
  const [out, setOut] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setOut(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return out;
}

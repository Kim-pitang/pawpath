import { useCallback, useEffect, useRef, useState } from 'react';
import type { Paged } from './types';

/** 페이지 단위 목록. key가 바뀌면 처음부터 다시 읽고, 더 보기는 뒤에 이어 붙인다. 응답이 늦게 와도 예전 조건의 결과를 쓰지 않는다. */
export function usePaged<P extends Paged<unknown>>(load: (page: number) => Promise<P>, key: string, enabled = true) {
  const [data, setData] = useState<P | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const loadRef = useRef(load);
  loadRef.current = load;
  const generation = useRef(0);

  const reload = useCallback(async () => {
    const current = (generation.current += 1);
    setError(null);
    try {
      const result = await loadRef.current(1);
      if (current === generation.current) setData(result);
    } catch (loadError) {
      if (current === generation.current) setError((loadError as Error).message);
    }
  }, []);

  useEffect(() => {
    if (enabled) void reload();
    return () => {
      generation.current += 1;
    };
  }, [key, enabled, reload]);

  const loadMore = useCallback(async () => {
    if (!data?.has_next || loadingMore) return;
    const current = generation.current;
    setLoadingMore(true);
    try {
      const next = await loadRef.current(data.page + 1);
      if (current === generation.current) setData({ ...next, items: [...data.items, ...next.items] });
    } catch (loadError) {
      if (current === generation.current) setError((loadError as Error).message);
    } finally {
      setLoadingMore(false);
    }
  }, [data, loadingMore]);

  return { data, setData, error, loadingMore, reload, loadMore };
}

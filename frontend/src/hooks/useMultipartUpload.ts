import { useCallback, useRef, useState } from "react";
import { createMultipart, signPart, completeMultipart, API_BASE } from "../lib/api";

const CHUNK_SIZE = 8 * 1024 * 1024; // 8MB
const CONCURRENCY = 2;

type UploadState = {
  isUploading: boolean;
  progress: number; // 0~1
  error: string | null;
  key?: string;
  uploadId?: string;
};

type PartItem = { partNumber: number; chunk: Blob };
type CompletedPart = { etag: string; partNumber: number };

export function useMultipartUpload() {
  const [state, setState] = useState<UploadState>({
    isUploading: false,
    progress: 0,
    error: null,
  });

  const aborters = useRef<AbortController[]>([]);

  const cancel = useCallback(() => {
    aborters.current.forEach((a) => a.abort());
    aborters.current = [];
    setState((s) => ({ ...s, isUploading: false, error: "Canceled" }));
  }, []);

  const start = useCallback(async (file: File) => {
    setState({ isUploading: true, progress: 0, error: null });

    try {
      const { uploadId, key } = await createMultipart(file.name, file.type || "application/octet-stream");
      setState((s) => ({ ...s, uploadId, key }));

      const parts: PartItem[] = [];
      for (let offset = 0, idx = 1; offset < file.size; offset += CHUNK_SIZE, idx++) {
        const chunk = file.slice(offset, Math.min(offset + CHUNK_SIZE, file.size));
        parts.push({ partNumber: idx, chunk });
      }

      let uploadedBytes = 0;
      const totalBytes = file.size;

      const results: CompletedPart[] = [];
      let i = 0;

      async function worker() {
        while (i < parts.length) {
          const myIndex = i++;
          const { partNumber, chunk } = parts[myIndex];

          const { url } = await signPart(key, uploadId, partNumber);

          const ab = new AbortController();
          aborters.current.push(ab);
          const res = await fetch(url, {
            method: "PUT",
            body: chunk,
            signal: ab.signal,
          });
          if (!res.ok) throw new Error(`PUT part ${partNumber} failed: ${res.status}`);

          const etag = res.headers.get("etag") || res.headers.get("ETag") || "";
          if (!etag) throw new Error(`Missing ETag for part ${partNumber}`);

          results.push({ etag, partNumber });

          uploadedBytes += chunk.size;
          setState((s) => ({ ...s, progress: Math.min(0.999, uploadedBytes / totalBytes) }));
        }
      }

      await Promise.all(Array.from({ length: CONCURRENCY }, () => worker()));

      results.sort((a, b) => a.partNumber - b.partNumber);
      await completeMultipart(key, uploadId, results);

      setState({ isUploading: false, progress: 1, error: null, key, uploadId });
      return { key, url: `${API_BASE}/videos/stream/${key}` };
    } catch (e: any) {
      setState((s) => ({ ...s, isUploading: false, error: e?.message ?? String(e) }));
      throw e;
    } finally {
      aborters.current = [];
    }
  }, []);

  return { ...state, start, cancel };
}

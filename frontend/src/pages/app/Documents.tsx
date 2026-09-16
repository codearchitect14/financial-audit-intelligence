/**
 * Document upload and listing.
 */

import { type ChangeEvent, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/api/client";
import { documents } from "@/api/endpoints";
import {
  Alert,
  Card,
  EmptyState,
  PageHeader,
  Skeleton,
  StatusBadge,
} from "@/components/ui";
import { formatBytes, formatDateTime } from "@/lib/format";
import { hasRole, useAuth } from "@/store/auth";
import type { DocumentRecord } from "@/api/types";

// Mirrors ALLOWED_UPLOAD_TYPES and MAX_UPLOAD_BYTES on the server. Checked here
// so a 25MB file is rejected before it is uploaded, not after. The server is
// still the authority; this only saves the round trip.
const ACCEPTED = ".pdf,.txt,.csv";
const MAX_BYTES = 25 * 1024 * 1024;

export default function DocumentsPage() {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const user = useAuth((state) => state.user);
  const canUpload = hasRole(user, "auditor");

  const list = useQuery({
    queryKey: ["documents"],
    queryFn: () => documents.list({ limit: 50 }),
  });

  const upload = useMutation<DocumentRecord, ApiError, File>({
    mutationFn: (file) => documents.upload(file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      if (inputRef.current) inputRef.current.value = "";
    },
  });

  function handleFile(event: ChangeEvent<HTMLInputElement>) {
    setLocalError(null);
    const file = event.target.files?.[0];
    if (!file) return;

    if (file.size > MAX_BYTES) {
      setLocalError(
        `That file is ${formatBytes(file.size)}. The limit is ${formatBytes(MAX_BYTES)}.`,
      );
      event.target.value = "";
      return;
    }
    upload.mutate(file);
  }

  return (
    <>
      <PageHeader
        title="Documents"
        description="Uploaded filings and audit notes. Indexed documents become searchable; indexing runs as a batch job and costs no model quota."
      />

      {canUpload && (
        <Card className="mb-6 p-5">
          <label htmlFor="document-upload" className="block text-sm font-medium text-ink-800">
            Upload a document
          </label>
          <input
            ref={inputRef}
            id="document-upload"
            type="file"
            accept={ACCEPTED}
            onChange={handleFile}
            disabled={upload.isPending}
            className="mt-2 block w-full text-sm text-ink-600 file:mr-4 file:rounded-lg file:border-0 file:bg-brand-600 file:px-4 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-brand-700 disabled:opacity-50"
          />
          <p className="mt-2 text-xs text-ink-500">
            PDF, plain text, or CSV, up to {formatBytes(MAX_BYTES)}. Re-uploading identical
            content reuses the existing document rather than duplicating it.
          </p>

          {upload.isPending && (
            <p className="mt-3 text-sm text-ink-500">Uploading and hashing...</p>
          )}
          {localError && (
            <div className="mt-3">
              <Alert tone="error">{localError}</Alert>
            </div>
          )}
          {upload.isError && (
            <div className="mt-3">
              <Alert tone="error" title="Upload rejected">
                {upload.error.message}
              </Alert>
            </div>
          )}
          {upload.isSuccess && (
            <div className="mt-3">
              <Alert tone="success">
                Stored {upload.data.original_filename}. Run the indexing job to make it
                searchable.
              </Alert>
            </div>
          )}
        </Card>
      )}

      <Card className="overflow-hidden">
        {list.isLoading ? (
          <div className="space-y-2 p-5">
            {Array.from({ length: 4 }, (_, index) => (
              <Skeleton key={index} className="h-12" />
            ))}
          </div>
        ) : (list.data?.total ?? 0) === 0 ? (
          <div className="p-6">
            <EmptyState
              title="No documents yet"
              description={
                canUpload
                  ? "Upload a filing or an audit note to make it searchable."
                  : "Nobody in your organization has uploaded a document yet. Auditors and admins can upload."
              }
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Uploaded documents</caption>
              <thead className="bg-ink-50 text-left text-xs uppercase tracking-wide text-ink-500">
                <tr>
                  <th scope="col" className="px-5 py-3 font-semibold">Filename</th>
                  <th scope="col" className="px-5 py-3 font-semibold">Type</th>
                  <th scope="col" className="px-5 py-3 font-semibold">Size</th>
                  <th scope="col" className="px-5 py-3 font-semibold">Passages</th>
                  <th scope="col" className="px-5 py-3 font-semibold">Status</th>
                  <th scope="col" className="px-5 py-3 font-semibold">Uploaded</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-200">
                {list.data?.items.map((document) => (
                  <tr key={document.id} className="transition hover:bg-ink-50">
                    <td className="max-w-xs truncate px-5 py-3 font-medium text-ink-900">
                      {document.original_filename}
                    </td>
                    <td className="px-5 py-3 capitalize text-ink-600">{document.doc_type}</td>
                    <td className="px-5 py-3 tabular-nums text-ink-600">
                      {formatBytes(document.size_bytes)}
                    </td>
                    <td className="px-5 py-3 tabular-nums text-ink-600">
                      {document.chunk_count || "not indexed"}
                    </td>
                    <td className="px-5 py-3">
                      <StatusBadge status={document.status} />
                    </td>
                    <td className="px-5 py-3 text-ink-600">
                      {formatDateTime(document.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

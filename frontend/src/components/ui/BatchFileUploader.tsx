import { useState, useRef, useCallback } from "react";
import { useI18n } from "../../i18n/context";

interface BatchFileUploaderProps {
  files: File[];
  onFilesAdd: (files: File[]) => void;
  onFileRemove: (index: number) => void;
  accept: string;
}

export default function BatchFileUploader({
  files,
  onFilesAdd,
  onFileRemove,
  accept,
}: BatchFileUploaderProps) {
  const { t } = useI18n();
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(true);
    },
    [],
  );

  const handleDragLeave = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
    },
    [],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
      const droppedFiles = Array.from(e.dataTransfer.files);
      if (droppedFiles.length > 0) {
        onFilesAdd(droppedFiles);
      }
    },
    [onFilesAdd],
  );

  const handleClick = useCallback(() => {
    inputRef.current?.click();
  }, []);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selected = Array.from(e.target.files ?? []);
      if (selected.length > 0) {
        onFilesAdd(selected);
      }
      // Reset so the same files can be re-selected
      e.target.value = "";
    },
    [onFilesAdd],
  );

  const borderClass = isDragging
    ? "border-blue-500 bg-blue-500/10"
    : "border-gray-600 border-dashed";

  return (
    <div className="flex flex-col gap-2">
      {/* Drop zone */}
      <div
        role="button"
        tabIndex={0}
        aria-label={t("batch_drop_aria")}
        onClick={handleClick}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") handleClick();
        }}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`flex items-center justify-center rounded-md border-2 cursor-pointer transition-colors ${borderClass} min-h-[120px]`}
      >
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple
          onChange={handleChange}
          className="hidden"
          aria-hidden="true"
        />
        <span className="text-sm text-gray-400 select-none">
          {t("batch_drop_hint")}
        </span>
      </div>

      {/* File count */}
      {files.length > 0 && (
        <p className="text-xs text-gray-400">
          {t("batch_file_count").replace("{count}", String(files.length))}
        </p>
      )}

      {/* File list */}
      {files.length > 0 && (
        <ul className="flex flex-col gap-1" aria-label={t("batch_file_list_label")}>
          {files.map((file, index) => (
            <li
              key={`${file.name}-${index}`}
              className="flex items-center justify-between rounded bg-gray-700/50 px-2 py-1 text-sm text-gray-300"
            >
              <span className="truncate mr-2">{file.name}</span>
              <button
                type="button"
                aria-label={t("batch_delete_file").replace("{name}", file.name)}
                onClick={() => onFileRemove(index)}
                className="shrink-0 text-gray-400 hover:text-red-400 transition-colors"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

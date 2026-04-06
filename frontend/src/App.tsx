import { useCallback, useState, type FormEvent } from "react";
import {
  createJob,
  fetchJobResult,
  fetchJobStatus,
  type BlockItem,
  type JobResultResponse,
} from "./api";

const POLL_MS = 1000;
const MAX_POLLS = 180;

function statusClass(status: string): string {
  switch (status) {
    case "queued":
      return "text-muted";
    case "running":
      return "text-blue-400";
    case "success":
      return "text-emerald-400";
    case "failed":
      return "text-red-400";
    default:
      return "text-muted";
  }
}

function BlockList({ blocks }: { blocks: BlockItem[] }) {
  if (!blocks.length) return null;
  return (
    <ul className="mt-3 flex list-none flex-col gap-2 p-0">
      {blocks.map((b, i) => (
        <li
          key={i}
          className="rounded-lg border border-border bg-[#0f1419] p-3 text-sm"
        >
          <span className="mr-2 font-mono text-xs text-muted">
            #{typeof b.index === "number" ? b.index : i}
          </span>
          <span className="text-xs uppercase tracking-wide text-blue-400">
            {b.type || "block"}
          </span>
          <p className="mt-1 whitespace-pre-wrap break-words text-[#e7edf4]">
            {b.text || ""}
          </p>
        </li>
      ))}
    </ul>
  );
}

export default function App() {
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<string | null>(null);
  const [hint, setHint] = useState<string>("");
  const [fullJson, setFullJson] = useState<string>("");
  const [blocks, setBlocks] = useState<BlockItem[]>([]);
  const [showResult, setShowResult] = useState(false);
  const [showStatus, setShowStatus] = useState(false);

  const copyJson = useCallback(() => {
    if (!fullJson) return;
    void navigator.clipboard.writeText(fullJson).catch(() => {
      setBanner("复制失败，请手动选择文本。");
    });
  }, [fullJson]);

  const onSubmit = useCallback(
    async (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      setBanner(null);
      setShowResult(false);
      setFullJson("");
      setBlocks([]);
      setShowStatus(false);

      const form = e.currentTarget;
      const input = form.elements.namedItem("file") as HTMLInputElement;
      const file = input.files?.[0];
      if (!file) {
        setBanner("请先选择文件。");
        return;
      }

      setBusy(true);
      try {
        const created = await createJob(file);
        setJobId(created.job_id);
        setJobStatus(created.status);
        setShowStatus(true);
        setHint("正在轮询状态…");

        let polls = 0;
        let terminal = false;
        while (!terminal && polls < MAX_POLLS) {
          await new Promise((r) => setTimeout(r, POLL_MS));
          polls += 1;
          const st = await fetchJobStatus(created.job_id);
          setJobStatus(st.status);
          if (st.status === "success" || st.status === "failed") {
            terminal = true;
          }
        }

        if (!terminal) {
          throw new Error("等待超时，请稍后在 OpenAPI 中按任务 ID 查询。");
        }

        const full: JobResultResponse = await fetchJobResult(created.job_id);
        setFullJson(JSON.stringify(full, null, 2));
        setBlocks(full.result?.blocks ?? []);
        setShowResult(true);
        setHint(
          full.status === "failed"
            ? "任务失败，请查看 JSON 中的 error 字段。"
            : "解析完成。"
        );
      } catch (err) {
        setBanner(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    []
  );

  return (
    <div className="mx-auto max-w-3xl px-5 py-10 pb-12">
      <header className="mb-7">
        <h1 className="mb-2 text-3xl font-semibold tracking-tight text-[#e7edf4]">
          文档解析
        </h1>
        <p className="text-sm text-muted">
          上传 PDF / DOCX / TXT / Markdown，异步解析后查看 JSON（含{" "}
          <code className="rounded bg-surface px-1 py-0.5 font-mono text-xs">
            blocks
          </code>
          ）
        </p>
      </header>

      <main className="rounded-[10px] border border-border bg-surface p-6">
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <label className="flex cursor-pointer flex-col gap-2">
            <span className="text-sm text-muted">选择文件</span>
            <input
              type="file"
              name="file"
              required
              disabled={busy}
              accept=".pdf,.docx,.txt,.md,.markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown"
              className="text-sm file:mr-3 file:cursor-pointer file:rounded-md file:border file:border-border file:bg-[#0f1419] file:px-3 file:py-2 file:text-sm file:text-[#e7edf4] hover:file:border-blue-500"
            />
          </label>
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-blue-500 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-blue-400 disabled:opacity-50"
          >
            {busy ? "处理中…" : "上传并开始解析"}
          </button>
        </form>

        {showStatus && jobId && (
          <section
            className="mt-6 border-t border-border pt-6"
            aria-live="polite"
          >
            <h2 className="mb-3 text-sm font-semibold text-muted">任务状态</h2>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              <dt className="text-muted">任务 ID</dt>
              <dd>
                <code className="rounded bg-[#0f1419] px-1.5 py-0.5 font-mono text-xs">
                  {jobId}
                </code>
              </dd>
              <dt className="text-muted">状态</dt>
              <dd className={`font-semibold ${statusClass(jobStatus ?? "")}`}>
                {jobStatus}
              </dd>
              <dt className="text-muted">说明</dt>
              <dd className="text-muted">{hint}</dd>
            </dl>
          </section>
        )}

        {showResult && fullJson && (
          <section className="mt-6 border-t border-border pt-6">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-muted">
                解析结果 JSON
              </h2>
              <button
                type="button"
                onClick={copyJson}
                className="rounded-lg border border-border px-3 py-1.5 text-xs text-blue-400 hover:border-blue-500"
              >
                复制 JSON
              </button>
            </div>
            <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-[#0f1419] p-4 font-mono text-xs leading-relaxed text-[#e7edf4]">
              {fullJson}
            </pre>
            <h3 className="mb-2 mt-5 text-sm font-semibold text-muted">
              内容块预览
            </h3>
            <BlockList blocks={blocks} />
          </section>
        )}

        {banner && (
          <p
            className="mt-5 rounded-lg border border-red-400/80 bg-red-500/10 px-4 py-3 text-sm text-red-200"
            role="alert"
          >
            {banner}
          </p>
        )}
      </main>

      <footer className="mt-8 text-center text-sm text-muted">
        <a href="/docs" className="text-blue-400 hover:underline">
          OpenAPI 文档
        </a>
        <span className="mx-2 opacity-50">·</span>
        <a href="/health" className="text-blue-400 hover:underline">
          健康检查
        </a>
      </footer>
    </div>
  );
}

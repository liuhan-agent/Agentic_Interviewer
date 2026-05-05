"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Flag, MessageSquare } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  createAnnotation,
  type AnnotationType,
  type AnnotationVerdict,
} from "@/lib/api/admin";

const ANNOTATION_TYPES: { value: AnnotationType; label: string }[] = [
  { value: "bad_question", label: "问题质量差" },
  { value: "wrong_score", label: "评分不准确" },
  { value: "rag_miss", label: "RAG 误召回" },
  { value: "verifier_error", label: "Verifier 误判" },
  { value: "other", label: "其他" },
];

const VERDICTS: { value: AnnotationVerdict; label: string; color: string }[] = [
  { value: "flagged", label: "标记问题", color: "text-amber-400" },
  { value: "approved", label: "确认正常", color: "text-emerald-400" },
  { value: "corrected", label: "已纠正", color: "text-sky-400" },
];

export function TraceAnnotationDialog({
  traceId,
  sessionId,
  turnIdx,
  generationTraceId,
  nodeName,
  onClose,
  onCreated,
}: {
  traceId: string;
  sessionId: string;
  turnIdx: number;
  generationTraceId?: number;
  nodeName?: string;
  onClose: () => void;
  onCreated?: () => void;
}) {
  const [type, setType] = useState<AnnotationType>("bad_question");
  const [verdict, setVerdict] = useState<AnnotationVerdict>("flagged");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const submit = useCallback(async () => {
    setSubmitting(true);
    setError(null);
    try {
      await createAnnotation({
        trace_id: traceId,
        session_id: sessionId,
        turn_idx: turnIdx,
        generation_trace_id: generationTraceId,
        node: nodeName,
        annotation_type: type,
        verdict,
        notes: notes.trim() || undefined,
      });
      setSuccess(true);
      onCreated?.();
      setTimeout(onClose, 1200);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }, [traceId, sessionId, turnIdx, generationTraceId, nodeName, type, verdict, notes, onClose, onCreated]);

  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !submitting) onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose, submitting]);

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  if (success) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" role="dialog" aria-modal="true" aria-label="标注已保存">
        <div className="rounded-xl border bg-card p-6 shadow-xl text-center space-y-2">
          <CheckCircle2 className="mx-auto h-8 w-8 text-emerald-400" />
          <p className="text-sm font-medium">标注已保存</p>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose} role="dialog" aria-modal="true" aria-label="人工标注">
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="w-full max-w-md rounded-xl border bg-card p-6 shadow-xl space-y-4 outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-sky-400" />
          <h3 className="font-semibold">人工标注</h3>
          <Badge variant="outline" className="font-mono text-[10px]">
            Turn {turnIdx}
          </Badge>
          {nodeName && (
            <Badge variant="secondary" className="font-mono text-[10px]">
              {nodeName}
            </Badge>
          )}
        </div>

        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">问题类型</p>
          <div className="flex flex-wrap gap-1.5">
            {ANNOTATION_TYPES.map((t) => (
              <button
                key={t.value}
                onClick={() => setType(t.value)}
                className={[
                  "rounded-md border px-2.5 py-1 text-xs transition-colors",
                  type === t.value
                    ? "border-primary bg-primary/10 text-primary font-medium"
                    : "border-border text-muted-foreground hover:bg-muted",
                ].join(" ")}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">判定</p>
          <div className="flex gap-2">
            {VERDICTS.map((v) => (
              <button
                key={v.value}
                onClick={() => setVerdict(v.value)}
                className={[
                  "flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs transition-colors",
                  verdict === v.value
                    ? `border-current/30 bg-current/5 font-medium ${v.color}`
                    : "border-border text-muted-foreground hover:bg-muted",
                ].join(" ")}
              >
                {v.value === "flagged" && <Flag className="h-3 w-3" />}
                {v.value === "approved" && <CheckCircle2 className="h-3 w-3" />}
                {v.value === "corrected" && <AlertTriangle className="h-3 w-3" />}
                {v.label}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">备注（可选）</p>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="描述问题或纠正建议..."
            rows={3}
            maxLength={2000}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>

        {error && (
          <p className="text-xs text-destructive">{error}</p>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            取消
          </Button>
          <Button size="sm" onClick={submit} disabled={submitting}>
            {submitting ? "提交中..." : "保存标注"}
          </Button>
        </div>
      </div>
    </div>
  );
}

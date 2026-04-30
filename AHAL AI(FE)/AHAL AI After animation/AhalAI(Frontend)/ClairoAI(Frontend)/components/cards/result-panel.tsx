"use client";

import {
  Target,
  Layers,
  Puzzle,
  Zap,
  AlertTriangle,
  FileText,
  Download,
  Copy,
  Check,
  GitBranch,
  Network,
} from "lucide-react";
import { useEffect, useState } from "react";
import { ResultCard } from "./result-card";
import type { AnalysisResult, SessionIntelligenceResponse } from "@/types";
import { downloadJSON, copyToClipboard, downloadPDF } from "@/lib/utils";
import { getSessionIntelligence, getSessionReport, syncChatContext } from "@/lib/api";
import { dispatchSessionFocus } from "@/lib/session";

interface ResultPanelProps {
  result: AnalysisResult;
}

const hasText = (value: unknown) => typeof value === "string" && value.trim().length > 0;

const hasRenderableValue = (value: unknown): boolean => {
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.some((item) => hasRenderableValue(item));
  if (value && typeof value === "object") return Object.values(value).some((item) => hasRenderableValue(item));
  return Boolean(value);
};

const renderValue = (value: any) => {
  if (!hasRenderableValue(value)) return null;

  if (typeof value === "string") return value;

  if (Array.isArray(value)) {
    return value.map((v, i) => <div key={i}>- {typeof v === "object" ? JSON.stringify(v) : String(v)}</div>);
  }

  if (typeof value === "object") {
    return value.description || JSON.stringify(value);
  }

  return String(value);
};

export function ResultPanel({ result }: ResultPanelProps) {
  const [copied, setCopied] = useState(false);
  const [intelligence, setIntelligence] = useState<SessionIntelligenceResponse | null>(null);
  const projectIntelligence = intelligence?.project as
    | (SessionIntelligenceResponse["project"] & { system_workflow?: AnalysisResult["system_workflow"] })
    | undefined;
  const fallbackWorkflows = result.workflows || [];
  const workflows = intelligence?.workflows?.length ? intelligence.workflows : fallbackWorkflows;
  const data = {
    ...result,
    system_workflow: projectIntelligence?.system_workflow ?? result.system_workflow,
    insights: Array.isArray(intelligence?.project?.insights) && intelligence.project.insights.length > 0
      ? intelligence.project.insights
      : Array.isArray(result.insights)
        ? result.insights
        : Array.isArray((result as AnalysisResult & { insight_list?: unknown[] }).insight_list)
          ? (result as AnalysisResult & { insight_list?: unknown[] }).insight_list
          : [],
    insight_list: Array.isArray((result as AnalysisResult & { insight_list?: unknown[] }).insight_list)
      ? (result as AnalysisResult & { insight_list?: unknown[] }).insight_list
      : [],
  };
  const workflow = data.system_workflow;
  const insights =
    data.insights ||
    (data as AnalysisResult & { insight_list?: unknown[] }).insight_list ||
    [];
  const graph = intelligence?.graph?.edges?.length || intelligence?.graph?.dependencies
    ? intelligence.graph
    : result.dependency_graph;
  const workflowConfidence = workflows?.[0]?.confidence_percent ?? null;
  const workflowReasons = workflows?.[0]?.uncertainty_reasons ?? [];
  const graphConfidence = graph?.confidence_percent ?? null;
  const graphReasons = graph?.uncertainty_reasons ?? [];
  const centralNodes = graph?.central_nodes?.slice(0, 4) ?? [];
  const dependencyEntries = graph?.dependencies
    ? Object.entries(graph.dependencies).slice(0, 6)
    : [];
  const summaryWhat = result.summary?.what || result.summary_blocks?.what || "";
  const summaryWhy = result.summary?.why || result.summary_blocks?.why || "";
  const displayProjectGoal = result.project_goal || summaryWhat || "N/A";
  const workflowSections = workflow
    ? [
        { label: "Initialization", value: renderValue(workflow.initialization) },
        { label: "Request Flow", value: renderValue(workflow.request_flow) },
        { label: "Processing Flow", value: renderValue(workflow.processing_flow) },
        { label: "Response Flow", value: renderValue(workflow.response_flow) },
      ].filter((section) => section.value)
    : [];
  const hasWorkflow = workflowSections.length > 0;
  const hasGraph = Boolean(graph?.nodes?.length || graph?.edges?.length || dependencyEntries.length);
  const validInsights = Array.isArray(insights)
    ? insights.filter((item) => {
        if (typeof item === "string") return item.trim().length > 0;
        if (item && typeof item === "object") {
          const candidate = item as { insight?: unknown; impact?: unknown };
          return hasText(candidate.insight) || hasText(candidate.impact);
        }
        return false;
      })
    : [];
  const hasInsights = validInsights.length > 0;

  useEffect(() => {
    console.log("API RESPONSE:", data);
    console.log("WORKFLOW:", data.system_workflow);
  }, [data]);

  useEffect(() => {
    let active = true;
    getSessionIntelligence(result.session_id)
      .then((payload) => {
        console.log("API RESPONSE:", payload);
        if (active) {
          setIntelligence(payload);
        }
      })
      .catch((error) => {
        console.error("API ERROR:", error);
        if (active) {
          setIntelligence(null);
        }
      });
    return () => {
      active = false;
    };
  }, [result.session_id]);

  const pushFocus = async (payload: { focus: string; module?: string; workflow?: string; file_path?: string }) => {
    try {
      await syncChatContext({
        session_id: result.session_id,
        mode: result.type,
        ...payload,
      });
      dispatchSessionFocus({
        sessionId: result.session_id,
        mode: result.type,
        focus: payload.focus,
        module: payload.module,
        workflow: payload.workflow,
        filePath: payload.file_path,
      });
    } catch (error) {
      console.error("API ERROR:", error);
    }
  };

  const handleCopy = async () => {
    const success = await copyToClipboard(JSON.stringify(result, null, 2));
    if (success) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleDownload = () => {
    downloadJSON(result, `clairo-analysis-${result.session_id}.json`);
  };

  const handleDownloadReport = async () => {
    try {
      const response = await getSessionReport(result.session_id);
      downloadPDF(response.report, `clairo-report-${result.session_id}.pdf`);
    } catch {
      const fallbackReport = [
        "=== 1. PROJECT OVERVIEW ===",
        `- What the project does: ${summaryWhat || "Not found in analyzed data"}`,
        `- Main purpose: ${result.project_goal || "Not found in analyzed data"}`,
        "",
        "=== 2. TECH STACK ===",
        "- Not found in analyzed data",
        "",
        "=== 3. ARCHITECTURE ===",
        `- System design style: ${result.architecture_style || "Not found in analyzed data"}`,
        `- High-level explanation: ${summaryWhy || "Not found in analyzed data"}`,
        "",
        "=== 4. CORE MODULES ===",
        ...(result.key_modules.length > 0 ? result.key_modules.map((item) => `- ${item}`) : ["- Not found in analyzed data"]),
        "",
        "=== 5. CORE FEATURES ===",
        ...(result.core_features.length > 0 ? result.core_features.map((item) => `- ${item}`) : ["- Not found in analyzed data"]),
        "",
        "=== 6. EXECUTION WORKFLOW ===",
        "1. User action enters the analyzed system",
        "2. Processing follows the analyzed architecture",
        "3. Core modules handle the main logic",
        "4. Data flows through the detected features",
        "5. Response is returned from the analyzed path",
        "",
        "=== 7. DATA FLOW ===",
        "- Not found in analyzed data",
        "",
        "=== 8. RISKS & LIMITATIONS ===",
        ...(result.risks.length > 0 ? result.risks.map((item) => `- ${item}`) : ["- Not found in analyzed data"]),
        "",
        "=== 9. IMPROVEMENT SUGGESTIONS ===",
        ...(result.summary_blocks?.remaining?.length
          ? result.summary_blocks.remaining.map((item) => `- ${item}`)
          : ["- Not found in analyzed data"]),
        "",
        "=== 10. FINAL SUMMARY ===",
        `- ${summaryWhat || result.project_goal || "Not found in analyzed data"}`,
      ].join("\n");
      downloadPDF(fallbackReport, `clairo-report-${result.session_id}.pdf`);
    }
  };

  return (
    <div className="space-y-6">
      {/* Actions Bar */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-200">
          Analysis Results
        </h2>
        <div className="flex items-center gap-2">
          <button
            onClick={handleCopy}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs text-slate-400 hover:text-slate-200 hover:bg-white/10 transition-all"
          >
            {copied ? (
              <Check className="w-3.5 h-3.5 text-emerald-400" />
            ) : (
              <Copy className="w-3.5 h-3.5" />
            )}
            {copied ? "Copied!" : "Copy JSON"}
          </button>
          <button
            onClick={handleDownload}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs text-slate-400 hover:text-slate-200 hover:bg-white/10 transition-all"
          >
            <Download className="w-3.5 h-3.5" />
            Download
          </button>
          <button
            onClick={() => {
              void handleDownloadReport();
            }}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs text-slate-400 hover:text-slate-200 hover:bg-white/10 transition-all"
          >
            <FileText className="w-3.5 h-3.5" />
            Report
          </button>
        </div>
      </div>

      {/* Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Project Goal */}
        <ResultCard icon={Target} title="Project Goal" delay={0}>
          <p className="text-slate-300">{displayProjectGoal}</p>
        </ResultCard>

        {/* Architecture */}
        <ResultCard icon={Layers} title="Architecture Style" delay={0.07}>
          <p className="text-slate-300">
            {result.architecture_style || "-"}
          </p>
        </ResultCard>

        {/* Key Modules */}
        <ResultCard icon={Puzzle} title="Key Modules" delay={0.14} variant="list">
          {result.key_modules.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {result.key_modules.map((mod, i) => (
                <button
                  key={i}
                  onClick={() => {
                    void pushFocus({
                      focus: `Now focusing on module ${mod}`,
                      module: mod,
                      file_path: mod,
                    });
                  }}
                  className="px-2.5 py-1 rounded-md bg-cyan-500/10 text-cyan-300 text-xs font-mono border border-cyan-500/20"
                >
                  {mod}
                </button>
              ))}
            </div>
          ) : (
            <p>No modules detected</p>
          )}
        </ResultCard>

        {/* Core Features */}
        <ResultCard icon={Zap} title="Core Features" delay={0.21} variant="list">
          {result.core_features.length > 0 ? (
            <ul className="space-y-1.5">
              {result.core_features.map((feat, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 mt-1.5 flex-shrink-0" />
                  <span className="text-slate-300">{feat}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p>No features detected</p>
          )}
        </ResultCard>

        {/* Risks */}
        <ResultCard icon={AlertTriangle} title="Risks" delay={0.28} variant="warning">
          {result.risks.length > 0 ? (
            <ul className="space-y-1.5">
              {result.risks.map((risk, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400 mt-1.5 flex-shrink-0" />
                  <span className="text-amber-200/80">{risk}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-emerald-400/70">No risks detected</p>
          )}
        </ResultCard>

        {/* Summary */}
        <ResultCard icon={FileText} title="Summary" delay={0.35}>
          <div className="space-y-3">
            {summaryWhat && (
              <div>
                <span className="text-xs font-semibold text-violet-400 uppercase tracking-wider">
                  What
                </span>
                <p className="text-slate-300 mt-0.5">
                  {summaryWhat}
                </p>
              </div>
            )}
            {summaryWhy && (
              <div>
                <span className="text-xs font-semibold text-violet-400 uppercase tracking-wider">
                  Why
                </span>
                <p className="text-slate-300 mt-0.5">
                  {summaryWhy}
                </p>
              </div>
            )}
            {result.summary_blocks?.remaining?.length > 0 && (
              <div>
                <span className="text-xs font-semibold text-violet-400 uppercase tracking-wider">
                  Remaining
                </span>
                <ul className="mt-1 space-y-1">
                  {result.summary_blocks.remaining.map((item, i) => (
                    <li key={i} className="text-slate-300 text-xs flex items-start gap-1.5">
                      <span className="text-violet-400 mt-0.5">-&gt;</span> {item}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {result.summary_blocks?.issues?.length > 0 && (
              <div>
                <span className="text-xs font-semibold text-amber-400 uppercase tracking-wider">
                  Issues
                </span>
                <ul className="mt-1 space-y-1">
                  {result.summary_blocks.issues.map((item, i) => (
                    <li key={i} className="text-amber-200/70 text-xs flex items-start gap-1.5">
                      <span className="text-amber-400 mt-0.5">!</span> {item}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {!summaryWhat &&
              !summaryWhy && (
                <p>No summary available</p>
              )}
            {result.confidence_score ? (
              <div className="rounded-xl border border-emerald-400/10 bg-emerald-400/5 px-3 py-2">
                <span className="text-xs font-semibold text-emerald-300 uppercase tracking-wider">
                  Confidence
                </span>
                <p className="mt-0.5 text-sm text-emerald-100">{result.confidence_score}%</p>
                {result.confidence_reasons?.length ? (
                  <p className="mt-1 text-xs text-emerald-100/70">
                    {result.confidence_reasons.slice(0, 2).join(", ")}
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>
        </ResultCard>

        {hasWorkflow ? (
          <ResultCard icon={GitBranch} title="System Workflow" delay={0.42} variant="list">
            <div className="space-y-3">
              {workflowConfidence ? (
                <div className="rounded-xl border border-cyan-400/10 bg-cyan-400/5 px-3 py-2 text-xs text-cyan-100">
                  <p className="font-semibold">Confidence: {workflowConfidence}%</p>
                  {workflowReasons.length ? (
                    <p className="mt-1 text-cyan-100/70">
                      {workflowReasons.slice(0, 2).join(", ")}
                    </p>
                  ) : null}
                </div>
              ) : null}
              {workflowSections.map((section) => (
                <div key={section.label} className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
                  <p className="text-sm font-semibold text-slate-100">{section.label}</p>
                  <div className="mt-1 text-xs text-slate-400">{section.value}</div>
                </div>
              ))}
            </div>
          </ResultCard>
        ) : null}

        {hasGraph ? (
          <ResultCard icon={Network} title="Dependency Graph" delay={0.49} variant="list">
            <div className="space-y-2">
              {graphConfidence ? (
                <div className="rounded-xl border border-violet-400/10 bg-violet-400/5 px-3 py-2 text-xs text-violet-100">
                  <p className="font-semibold">Confidence: {graphConfidence}%</p>
                  {graphReasons.length ? (
                    <p className="mt-1 text-violet-100/70">
                      {graphReasons.slice(0, 2).join(", ")}
                    </p>
                  ) : null}
                </div>
              ) : null}
              {centralNodes.length ? (
                <div className="rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-slate-500">Core Modules</p>
                  <p className="mt-1 text-xs text-slate-300">{centralNodes.join(", ")}</p>
                </div>
              ) : null}
              {graph?.edges?.length
                ? graph.edges.slice(0, 6).map((edge, index) => (
                    <button
                      key={`${edge.source}-${edge.target}-${index}`}
                      onClick={() => {
                        void pushFocus({
                          focus: `Now focusing on relationship ${edge.source} to ${edge.target}`,
                          module: edge.source,
                        });
                      }}
                      className="w-full rounded-lg border border-white/8 bg-white/[0.03] px-3 py-2 text-left text-xs text-slate-300 transition-all hover:border-cyan-400/20 hover:bg-cyan-400/5"
                    >
                      {edge.source} {"->"} {edge.target}
                      <span className="ml-2 text-slate-500">({edge.relation})</span>
                    </button>
                  ))
                : dependencyEntries.map(([source, targets], index) => (
                    <button
                      key={`${source}-${index}`}
                      onClick={() => {
                        void pushFocus({
                          focus: `Now focusing on dependency path from ${source}`,
                          module: source,
                        });
                      }}
                      className="w-full rounded-lg border border-white/8 bg-white/[0.03] px-3 py-2 text-left text-xs text-slate-300 transition-all hover:border-cyan-400/20 hover:bg-cyan-400/5"
                    >
                      {source} {"->"} {(targets && targets[0]) || "dependency"}
                    </button>
                  ))}
            </div>
          </ResultCard>
        ) : null}

        {hasInsights ? (
          <ResultCard icon={Zap} title="Insights" delay={0.56} variant="list">
            <div className="space-y-3">
              {validInsights.map((item, index) => {
                const insightText =
                  typeof item === "object" && item !== null
                    ? String((item as { insight?: unknown }).insight || "")
                    : String(item);
                const impactText =
                  typeof item === "object" && item !== null
                    ? String((item as { impact?: unknown }).impact || "")
                    : "";

                return (
                  <div
                    key={`${insightText || index}-${index}`}
                    className="rounded-xl border border-white/8 bg-white/[0.03] p-3"
                  >
                    <p className="text-sm font-semibold text-slate-100">{insightText}</p>
                    {hasText(impactText) ? (
                      <p className="mt-1 text-xs text-slate-400">{impactText}</p>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </ResultCard>
        ) : null}
      </div>
    </div>
  );
}

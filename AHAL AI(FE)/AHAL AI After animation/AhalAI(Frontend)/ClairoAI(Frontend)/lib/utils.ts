import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: date.getFullYear() !== now.getFullYear() ? "numeric" : undefined,
  });
}

export function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 3) + "...";
}

export function downloadJSON(data: object, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function downloadText(text: string, filename: string) {
  const blob = new Blob([text], {
    type: "text/plain;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function escapePdfText(text: string): string {
  return text
    .replace(/\\/g, "\\\\")
    .replace(/\(/g, "\\(")
    .replace(/\)/g, "\\)")
    .replace(/\r/g, "");
}

function wrapPdfLine(text: string, maxChars = 92): string[] {
  const normalized = text.replace(/\t/g, "  ");
  if (!normalized.trim()) {
    return [""];
  }

  const words = normalized.split(/\s+/);
  const lines: string[] = [];
  let current = "";

  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length <= maxChars) {
      current = candidate;
      continue;
    }

    if (current) {
      lines.push(current);
      current = word;
      continue;
    }

    lines.push(word.slice(0, maxChars));
    current = word.slice(maxChars);
  }

  if (current) {
    lines.push(current);
  }

  return lines.length > 0 ? lines : [""];
}

export function downloadPDF(text: string, filename: string) {
  const pageWidth = 595;
  const pageHeight = 842;
  const margin = 48;
  const lineHeight = 16;
  const fontSize = 11;
  const usableWidthChars = 92;

  const wrappedLines = text
    .split("\n")
    .flatMap((line) => wrapPdfLine(line, usableWidthChars));

  const pages: string[][] = [];
  let currentPage: string[] = [];
  let y = pageHeight - margin;

  for (const line of wrappedLines) {
    if (y < margin) {
      pages.push(currentPage);
      currentPage = [];
      y = pageHeight - margin;
    }

    currentPage.push(`BT /F1 ${fontSize} Tf ${margin} ${y} Td (${escapePdfText(line)}) Tj ET`);
    y -= lineHeight;
  }

  if (currentPage.length === 0) {
    currentPage.push(`BT /F1 ${fontSize} Tf ${margin} ${pageHeight - margin} Td () Tj ET`);
  }
  pages.push(currentPage);

  const objects: string[] = [];
  objects.push("1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj");

  const kidsRefs = pages.map((_, index) => `${3 + index} 0 R`).join(" ");
  objects.push(`2 0 obj << /Type /Pages /Count ${pages.length} /Kids [${kidsRefs}] >> endobj`);

  const contentStartIndex = 3 + pages.length;
  pages.forEach((_, index) => {
    const contentRef = `${contentStartIndex + index} 0 R`;
    objects.push(
      `${3 + index} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidth} ${pageHeight}] /Resources << /Font << /F1 ${contentStartIndex + pages.length} 0 R >> >> /Contents ${contentRef} >> endobj`
    );
  });

  pages.forEach((pageLines, index) => {
    const stream = pageLines.join("\n");
    objects.push(
      `${contentStartIndex + index} 0 obj << /Length ${stream.length} >> stream\n${stream}\nendstream endobj`
    );
  });

  objects.push(
    `${contentStartIndex + pages.length} 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Courier >> endobj`
  );

  let pdf = "%PDF-1.4\n";
  const offsets: number[] = [0];
  for (const object of objects) {
    offsets.push(pdf.length);
    pdf += `${object}\n`;
  }

  const xrefStart = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n`;
  pdf += "0000000000 65535 f \n";
  for (let index = 1; index <= objects.length; index++) {
    pdf += `${String(offsets[index]).padStart(10, "0")} 00000 n \n`;
  }
  pdf += `trailer << /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF`;

  const blob = new Blob([pdf], { type: "application/pdf" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

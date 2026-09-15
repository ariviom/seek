import type { ReactNode } from "react";
import type { Citation } from "@/lib/api";
import { playOnPlainClick } from "@/lib/playback";

const linkClass = "font-medium underline decoration-muted-foreground/50 underline-offset-4 hover:decoration-foreground";

// Enough inline Markdown for grounded answers: links, bare URLs, bold, italics, and inline code. Everything else shows
// as written. A bare URL leaves off sentence punctuation that follows it; an underscore inside a word isn't italics.
const inline =
  /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)|(https?:\/\/[^\s)]*[^\s).,;:!?])|\*\*([^*]+)\*\*|\*([^*\s](?:[^*]*[^*\s])?)\*|(?<!\w)_([^_\s](?:[^_]*[^_\s])?)_(?!\w)|`([^`]+)`/g;

// The watch link forms the server reads Citations from (`chat.citation_links`), matched the same way.
const youtubeLink = /(?:https?:\/\/)?(?:(?:www\.|m\.)?youtube\.com\/watch\?([^\s)\]>"']+)|youtu\.be\/([\w-]+)(?:\?([^\s)\]>"']*))?)/;
const timestamp = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?$/;

// The saved Citation a link points to, if any: links to Videos outside the scope, or made up, are plain links.
export function citationOf(href: string, citations: Citation[]): Citation | undefined {
  const link = youtubeLink.exec(href);
  if (link === null) return undefined;
  const [, query, shortId, shortQuery] = link;
  const params = new URLSearchParams((query ?? shortQuery ?? "").replace(/[.,;:!?]+$/, "").replaceAll("&amp;", "&"));
  const videoId = shortId ?? params.get("v") ?? "";
  const time = timestamp.exec(params.get("t") ?? "");
  if (!/^[\w-]+$/.test(videoId) || time === null) return undefined;
  const [, hours, minutes, secs] = time;
  const seconds = Number(hours ?? 0) * 3600 + Number(minutes ?? 0) * 60 + Number(secs ?? 0);
  return citations.find((c) => c.youtube_video_id === videoId && c.seconds === seconds);
}

const bulletItem = /^\s*[-*+]\s+(.*)$/;
const numberedItem = /^\s*(\d+)[.)]\s+(.*)$/;
const headingLine = /^(#{1,6})\s+(.*)$/;

function startsBlock(line: string): boolean {
  return headingLine.test(line) || bulletItem.test(line) || numberedItem.test(line);
}

export function Markdown({
  text,
  citations,
  onPlay,
}: {
  text: string;
  citations: Citation[];
  onPlay: (citation: Citation) => void;
}) {
  return <div className="space-y-3 text-sm leading-6">{renderMarkdown(text, citations, onPlay)}</div>;
}

// Block Markdown: headings, bullet and numbered lists, and paragraphs split by blank lines. Lines within a paragraph
// keep their breaks, and an indented line continues the list item above it.
function renderMarkdown(text: string, citations: Citation[], onPlay: (citation: Citation) => void): ReactNode {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  const inlineOf = (source: string) => renderInline(source, citations, onPlay);
  let i = 0;
  // Takes lines from the current one while they pass the test.
  const take = (test: (line: string) => boolean): string[] => {
    const taken: string[] = [];
    for (let line = lines[i]; line !== undefined && test(line); line = lines[++i]) taken.push(line);
    return taken;
  };
  for (let line = lines[i]; line !== undefined; line = lines[i]) {
    const key = i;
    const heading = headingLine.exec(line);
    const numbered = numberedItem.exec(line);
    if (line.trim() === "") {
      i++;
    } else if (heading !== null) {
      i++;
      blocks.push(
        <h4 key={key} className={heading[1]?.length === 1 ? "text-base font-semibold" : "font-semibold"}>
          {inlineOf(heading[2] ?? "")}
        </h4>,
      );
    } else if (numbered !== null || bulletItem.test(line)) {
      const item = numbered === null ? bulletItem : numberedItem;
      const items: string[] = [];
      for (let next = lines[i]; next !== undefined && item.test(next); next = lines[i]) {
        i++;
        const continuation = take((more) => /^\s+\S/.test(more) && !startsBlock(more)).map((more) => more.trim());
        items.push([item.exec(next)?.at(-1) ?? "", ...continuation].join("\n"));
      }
      const children = items.map((source, index) => (
        <li key={index} className="whitespace-pre-line">
          {inlineOf(source)}
        </li>
      ));
      blocks.push(
        numbered === null ? (
          <ul key={key} className="list-disc space-y-1 pl-6">
            {children}
          </ul>
        ) : (
          <ol key={key} start={Number(numbered[1])} className="list-decimal space-y-1 pl-6">
            {children}
          </ol>
        ),
      );
    } else {
      const paragraph = take((next) => next.trim() !== "" && !startsBlock(next));
      blocks.push(
        <p key={key} className="whitespace-pre-line">
          {inlineOf(paragraph.join("\n"))}
        </p>,
      );
    }
  }
  return blocks;
}

function renderInline(text: string, citations: Citation[], onPlay: (citation: Citation) => void): ReactNode {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(inline)) {
    parts.push(text.slice(last, match.index));
    const [whole, label, labelled, bare, bold, starred, underscored, code] = match;
    const key = match.index;
    const href = labelled ?? bare;
    if (href !== undefined) {
      const citation = citationOf(href, citations);
      parts.push(
        <a
          key={key}
          className={linkClass}
          href={href}
          target="_blank"
          rel="noreferrer"
          title={citation && "Plays here; Ctrl- or ⌘-click opens YouTube"}
          onClick={(e) => citation && playOnPlainClick(e, () => onPlay(citation))}
        >
          {label ?? bare}
        </a>,
      );
    } else if (bold !== undefined) {
      // Models often bold a cited claim, link included.
      parts.push(
        <strong key={key} className="font-semibold">
          {renderInline(bold, citations, onPlay)}
        </strong>,
      );
    } else if (starred !== undefined || underscored !== undefined) {
      parts.push(<em key={key}>{renderInline(starred ?? underscored ?? "", citations, onPlay)}</em>);
    } else {
      parts.push(
        <code key={key} className="rounded-sm bg-muted px-1 font-mono text-[13px]">
          {code}
        </code>,
      );
    }
    last = match.index + whole.length;
  }
  parts.push(text.slice(last));
  return parts;
}

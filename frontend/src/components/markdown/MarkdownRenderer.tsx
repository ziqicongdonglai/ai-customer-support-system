import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import Code from "./Code";
import Pre from "./Pre";

interface MarkdownRendererProps {
  children: string;
}

export default function MarkdownRenderer({ children }: MarkdownRendererProps) {
  return (
    <div
      className="
        prose
        prose-sm
        max-w-none

        prose-headings:my-2
        prose-headings:font-semibold

        prose-p:my-2

        prose-ul:my-2
        prose-ol:my-2

        prose-li:my-0

        prose-pre:my-2

        prose-code:text-sm
      "
    >
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          pre: Pre,
          code: Code,
        }}
      >
        {children}
      </Markdown>
    </div>
  );
}

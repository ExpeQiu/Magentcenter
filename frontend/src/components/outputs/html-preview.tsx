"use client";

interface HtmlPreviewProps {
  content: string;
  title?: string;
}

/** 沙箱 iframe 渲染 HTML 文档（禁脚本） */
export function HtmlPreview({ content, title }: HtmlPreviewProps) {
  return (
    <iframe
      title={title || "HTML 预览"}
      srcDoc={content}
      sandbox=""
      className="min-h-0 w-full flex-1 border-0 bg-white"
      referrerPolicy="no-referrer"
    />
  );
}

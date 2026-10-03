interface CodeProps {
  inline?: boolean;
  className?: string;
  children?: React.ReactNode;
}

export default function Code({ inline, className, children }: CodeProps) {
  if (inline) {
    return (
      <code
        className="
          rounded
          bg-gray-200
          px-1
          py-0.5
          text-sm
        "
      >
        {children}
      </code>
    );
  }

  return <code className={className}>{children}</code>;
}
